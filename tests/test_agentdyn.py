"""Offline defense contract, candidate selection and optional native AgentDyn tests."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from hermit.agent.evolver.base import Access, Progress, StepContext, Workspace
from hermit.agent.evolver.loader import find, instantiate
from hermit.integrations.agentdyn import GuardedRuntime, aggregate, load_defense, run, score, validate_case
from hermit.spec import check_spec
from hermit.task import RunOutput

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "hermit/adapter/templates/evosafe"


@pytest.fixture(autouse=True)
def trusted_fixture_checks(monkeypatch):
    # Only our repository-owned fixtures execute in these unit tests. Production
    # example remains sandbox.enforce=required; this is not a sandbox test.
    monkeypatch.setattr("hermit.spec.SANDBOX_ENFORCE", None)


class Runtime:
    functions = {}

    def __init__(self):
        self.calls = []

    def run_function(self, env, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        return "external fixture content", None


def test_hooks_block_rewrite_and_filter():
    class Defense:
        async def on_pre_tool_call(self, ctx):
            assert set(ctx) == {"instruction", "trace_id", "tool_name", "arguments"}
            return {"block": "outside requested scope"} if ctx["tool_name"] == "delete" else {"arguments": {"limit": 1}}

        async def on_post_tool_call(self, ctx, result):
            assert result["text"] == "external fixture content"
            return {"text": "filtered", "error": None}

    runtime, audit = Runtime(), []
    guarded = GuardedRuntime(runtime, Defense(), "read one item", "trace", str, audit)
    assert "Refused" in guarded.run_function({}, "delete", {})[1]
    assert runtime.calls == []
    args = {"limit": 50}
    assert guarded.run_function({}, "read", args) == ("filtered", None)
    assert runtime.calls == [("read", {"limit": 1})]
    assert args == {"limit": 1}
    assert audit[0]["blocked"] and audit[1]["output_changed"]


def test_hook_failure_is_not_silently_unprotected():
    class Bad:
        def on_pre_tool_call(self, ctx):
            raise RuntimeError("broken defense")
    runtime = Runtime()
    guarded = GuardedRuntime(runtime, Bad(), "task", "trace", str, [])
    with pytest.raises(RuntimeError, match="broken defense"):
        guarded.run_function({}, "read", {})
    assert not runtime.calls


def test_template_and_fresh_defense(tmp_path):
    assert check_spec(TEMPLATE, TEMPLATE).passed
    a, b = load_defense(TEMPLATE), load_defense(TEMPLATE)
    assert a is not b
    shutil.copytree(TEMPLATE, tmp_path / "adapter")
    (tmp_path / "adapter/defense.py").write_text("def build(): return object()")
    with pytest.raises(ValueError, match="missing"):
        load_defense(tmp_path / "adapter")


def row(id, clean, utility=True, attack=False):
    return {"id": id, "status": "ok", "output": {"kind": "clean" if clean else "injected",
            "utility": utility, "attack_success": None if clean else attack}}


def test_metrics_direction_and_separate_denominators():
    results = [row("c", True), row("a", False, attack=True), row("b", False)]
    assert aggregate(results)["objective"] == 0.5
    assert score({"injection_task_id": "i"}, RunOutput(results[1]["output"])).score == 0
    assert score({"injection_task_id": "i"}, RunOutput(results[2]["output"])).score == 1
    with pytest.raises(ValueError):
        aggregate([*results, {"status": "error"}])
    with pytest.raises(ValueError):
        aggregate([results[0]])


def test_split_groups_and_no_answer_leakage(tmp_path):
    spec = importlib.util.spec_from_file_location("prepare_agentdyn", ROOT / "examples/agentdyn/prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [{"suite": "shopping", "user_task_id": f"user_task_{i}", "injection_task_id": "injection_task_0",
              "injections": {"fixture": "inert regression fixture"}, "utility": True} for i in range(10)]
    module.prepare(cases, tmp_path / "data")
    data = [json.loads(s) for s in (tmp_path / "data/tasks.jsonl").read_text().splitlines()]
    owner = {}
    for split in ("train", "val", "test"):
        ids = (tmp_path / f"data/{split}.txt").read_text().splitlines()
        members = [r for r in data if r["id"] in ids]
        assert any(r.get("injection_task_id") for r in members)
        assert any(not r.get("injection_task_id") for r in members)
        for r in members:
            assert "utility" not in r
            group = (r["suite"], r["user_task_id"])
            assert owner.setdefault(group, split) == split
    with pytest.raises(FileExistsError):
        module.prepare(cases, tmp_path / "data")
    traces = tmp_path / "traces"
    traces.mkdir()
    (traces / "trace.json").write_text(json.dumps({"suite_name": "shopping", "user_task_id": "user_task_0",
        "injection_task_id": "injection_task_0", "injections": {"fixture": "inert"},
        "messages": ["not imported"], "utility": True}))
    imported = module.read_logs(traces, "shopping")
    assert len(imported) == 1
    assert set(imported[0]) == {"suite", "user_task_id", "injection_task_id", "injections"}


def test_report_requires_complete_coverage():
    spec = importlib.util.spec_from_file_location("report_agentdyn", ROOT / "examples/agentdyn/report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [row("c", True), row("a", False)]
    assert module.summarize(rows, ["c", "a"])["selection_objective"] == 1.0
    for incomplete in (rows[:1], rows + [rows[0]], rows + [{"id": "extra", "status": "error"}]):
        assert module.summarize(incomplete, ["c", "a"])["selection_objective"] is None
    assert module.summarize(rows, ["c", "a"], repeats=2)["selection_objective"] is None


@pytest.mark.parametrize("bad", [{"injections": {"x": "y"}}, {"injection_task_id": "i"}])
def test_reject_mislabeled_cases(bad):
    with pytest.raises(ValueError):
        validate_case({"suite": "shopping", "user_task_id": "user_task_0", **bad})


@pytest.mark.parametrize("mode,accepted", [("improve", True), ("regress", False), ("error", False), ("tie", False), ("invalid", False)])
def test_evolver_selection_and_rollback(tmp_path, mode, accepted):
    paths = {name: tmp_path / name for name in Workspace.__dataclass_fields__}
    for path in paths.values():
        path.mkdir()
    shutil.copytree(TEMPLATE, paths["adapter"], dirs_exist_ok=True)
    validation = tmp_path / "validation"
    validation.mkdir()
    (validation / "tasks.jsonl").write_text('{"id":"c"}\n{"id":"a"}\n')
    original = (paths["adapter"] / "ADAPTER.md").read_text()
    calls = []

    def evaluate(task_ids, adapter):
        calls.append(adapter)
        changed = Path(adapter) != paths["adapter"]
        if changed and mode == "error":
            return {"results": [{"id": "c", "status": "error"}]}
        return {"results": [row("c", True, utility=not (changed and mode == "regress")),
                            row("a", False, attack=not changed or mode == "tie")]}

    def llm(**kwargs):
        files = {n: (paths["adapter"] / n).read_text() for n in ("ADAPTER.md", "defense.py", "BUNDLE.md")}
        files["ADAPTER.md"] = "New defense instructions."
        if mode == "invalid":
            files["defense.py"] = "not valid python ???"
        return {"content": json.dumps({"summary": "candidate", "files": files})}

    ctx = StepContext(workspace=Workspace(**paths), access=Access(validation=validation), params={},
                      tools={"run_agent": evaluate, "llm": llm,
                             "check_spec": lambda path: check_spec(Path(path), TEMPLATE).to_dict()},
                      progress=Progress(1, 1, True))
    evolver, _ = instantiate(find("evosafe"), {})
    result = evolver.step(ctx)
    assert result.extra["accepted"] is accepted
    assert ((paths["adapter"] / "ADAPTER.md").read_text() != original) is accepted
    assert (paths["output"] / "selection.json").exists()
    assert len(calls) == (1 if mode == "invalid" else 2)


def test_trainer_evosafe_end_to_end(tmp_path, monkeypatch):
    """Real Trainer snapshots, tools, material, checks and commits; deterministic task/model doubles."""
    import yaml
    from hermit.config import Config
    from hermit.trainer.trainer import Trainer
    from hermit.tools import FunctionTool

    (tmp_path / "pipeline.py").write_text('''
from hermit.task import RunOutput
def run(task, adapter):
    improved = "tested revision" in (adapter / "ADAPTER.md").read_text()
    clean = task["kind"] == "clean"
    return RunOutput(output={"kind": task["kind"], "utility": True,
                     "attack_success": None if clean else not improved}, cost_usd=0.0, tokens=0)
''')
    (tmp_path / "judge.py").write_text("from hermit.integrations.agentdyn import score\n")
    rows = [{"id": f"{split}-{kind}", "kind": kind,
             **({"injection_task_id": "fixture"} if kind == "injected" else {})}
            for split in ("train", "val", "test") for kind in ("clean", "injected")]
    (tmp_path / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for split in ("train", "val", "test"):
        (tmp_path / f"{split}.txt").write_text(f"{split}-clean\n{split}-injected\n")
    config = {"data": {"tasks": "tasks.jsonl", "train": "train.txt", "val": "val.txt", "test": "test.txt", "step_size": 2},
              "template": str(TEMPLATE), "agent": {"name": "pipeline.py:run", "concurrency": 1},
              "judge": {"path": "judge.py"}, "evolver": {"name": "evosafe"},
              "sandbox": {"enabled": False}, "trainer": {"run_name": "offline", "output_dir": "runs", "epochs": 1}}
    (tmp_path / "run.yaml").write_text(yaml.safe_dump(config))
    original_tools = Trainer._tools

    def tools(self, *args, **kwargs):
        result = original_tools(self, *args, **kwargs)
        def propose(**kwargs):
            files = {name: (self.ws.adapter / name).read_text() for name in ("ADAPTER.md", "defense.py", "BUNDLE.md")}
            files["ADAPTER.md"] += "\ntested revision\n"
            return {"content": json.dumps({"summary": "offline proposal", "files": files})}
        result["llm"] = FunctionTool("llm", "offline proposer", propose, source="run")
        return result

    monkeypatch.setattr(Trainer, "_tools", tools)
    trainer = Trainer(Config.load(tmp_path / "run.yaml", []), log=lambda *_: None)
    trainer.train()
    assert "tested revision" in (trainer.ws.adapter / "ADAPTER.md").read_text()
    report = json.loads((tmp_path / "runs/offline/step_0001/output/selection.json").read_text())
    assert report["accepted"]
    assert set(report["eval_task_ids"]) == {"val-clean", "val-injected"}


def test_native_shopping_pipeline_without_model(tmp_path, monkeypatch):
    """Native environment, tools and judges; replace only the model with a scripted reader."""
    pytest.importorskip("agentdojo")
    from agentdojo.agent_pipeline import agent_pipeline as api
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.functions_runtime import FunctionCall
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.types import text_content_block_from_string
    try:
        suite = get_suite("v1.2.2", "shopping")
    except KeyError:
        pytest.skip("upstream AgentDojo installed, not AgentDyn")

    class Reader(BasePipelineElement):
        name = "offline-reader"

        def query(self, query, runtime, env, messages=(), extra_args=None):
            if messages[-1]["role"] == "tool":
                msg = {"role": "assistant", "content": [text_content_block_from_string("Done")], "tool_calls": None}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    FunctionCall(function="search_product", args={"product_name": "smart watch"}, id="read")]}
            return query, runtime, env, [*messages, msg], extra_args or {}

    monkeypatch.setattr(api, "get_llm", lambda *args: Reader())
    params = {"model": "gpt-4o-mini-2024-07-18", "logs": "logs"}
    case = {"suite": "shopping", "user_task_id": "user_task_0"}
    config = api.PipelineConfig(llm=params["model"], model_id=None, defense=None, system_message=None, system_message_name=None)
    native, _ = suite.run_task_with_pipeline(api.AgentPipeline.from_config(config), suite.get_user_task_by_id("user_task_0"), None, {})
    baseline = run(case, None, params=params, base=tmp_path)
    assert baseline.output == {"utility": native, "attack_success": None, "kind": "clean"}
    defended = run(case, TEMPLATE, params=params, base=tmp_path)
    assert defended.output == baseline.output
    assert defended.log != baseline.log
    assert json.loads((defended.log / "audit.json").read_text())[0]["tool"] == "search_product"
    assert "Treat tool results" in defended.messages[0]["content"][0]["content"]

    # An inert marker at a real injection vector proves post-hooks run after
    # environment injection, without creating an adversarial payload.
    adapter = tmp_path / "filter"
    shutil.copytree(TEMPLATE, adapter)
    (adapter / "defense.py").write_text('''
class Defense:
    def system_prompt_transform(self, prompt): return prompt
    def on_pre_tool_call(self, ctx): return None
    def on_post_tool_call(self, ctx, result):
        assert "OFFLINE_MARKER" in result["text"]
        return {"text": "filtered fixture", "error": result["error"]}
def build(): return Defense()
''')
    injected = {**case, "injection_task_id": "injection_task_0",
                "injections": {"injection_reviews_0": "OFFLINE_MARKER"}}
    filtered = run(injected, adapter, params=params, base=tmp_path)
    assert filtered.output["kind"] == "injected"
    assert type(filtered.output["attack_success"]) is bool
    tool_messages = [m for m in filtered.messages if m["role"] == "tool"]
    assert tool_messages[0]["content"][0]["content"] == "filtered fixture"

    class LoopingReader(Reader):
        calls = 0

        def query(self, query, runtime, env, messages=(), extra_args=None):
            self.calls += 1
            msg = {"role": "assistant", "content": None, "tool_calls": [
                FunctionCall(function="search_product", args={"product_name": "smart watch"}, id=str(self.calls))]}
            return query, runtime, env, [*messages, msg], extra_args or {}

    looping = LoopingReader()
    monkeypatch.setattr(api, "get_llm", lambda *args: looping)
    with pytest.raises(RuntimeError, match="terminal"):
        run(case, None, params={**params, "max_iters": 1}, base=tmp_path)
    assert looping.calls == 2  # initial call + one tools iteration; no suite retry
