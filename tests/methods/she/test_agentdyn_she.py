"""Offline checks of the upstream SHE bridge and held-out selection."""
import json
from pathlib import Path
import shutil
import sys
import os
from dataclasses import replace

import pytest

pytest.importorskip("she", reason="install the pinned she dependency group")

from hermit.agent.evolver.methods.she.evolver import SHEEvolver, call_model, diagnosis_schema, parse_object, training_records
from hermit.agent.evolver.base import Access, Progress, StepContext, Workspace
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "examples/agentdyn/utils"))
from bridge import GuardedRuntime, _run_episode as run
from hermit.agent.evolver.methods.she.runtime import ARTIFACTS, SHEDefense, validate_bundle
from hermit.spec import check_spec

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "hermit/adapter/templates/she"


@pytest.fixture(autouse=True)
def trusted_checks(monkeypatch):
    monkeypatch.setattr("hermit.spec.SANDBOX_ENFORCE", None)


def test_template_and_active_memory():
    assert check_spec(TEMPLATE, TEMPLATE).passed
    a, b = SHEDefense(TEMPLATE), SHEDefense(TEMPLATE)
    assert a.adapter.state is not b.adapter.state
    prompt = a.system_prompt_transform("Native instructions")
    assert "Native instructions" in prompt and "SHE Runtime Harness" in prompt
    assert a.adapter.state.memory_hits
    assert not b.adapter.state.memory_hits


def test_pre_tool_blocks_before_side_effect_and_escalation_is_conservative():
    class Runtime:
        functions = {"file_write": object(), "send_email": object()}
        calls = 0

        def run_function(self, *args):
            self.calls += 1
            return "unused", None

    runtime, defense = Runtime(), SHEDefense(TEMPLATE)
    defense.prepare_query("Read one public item")
    facade = GuardedRuntime(runtime, defense, "Read one public item", "test", str, [])
    _, error = facade.run_function({}, "file_write", {"path": "/etc/test-fixture"})
    assert "Refused" in error and runtime.calls == 0
    defense.adapter.state.last_untrusted = True
    _, error = facade.run_function({}, "send_email", {"to": "reader@example.org", "body": "public note"})
    assert "Refused" in error and runtime.calls == 0
    assert defense.export_state()["judge_calls"]


def row(case_id, clean, utility=True, attack=False):
    verdict = {"kind": "clean" if clean else "injected", "utility": utility, "attack_success": None if clean else attack}
    return {"judge": {"extra": {"metrics": verdict}}, "id": case_id, "status": "ok", "input": {} if clean else {"injection_task_id": "fixture"},
            "messages": [{"role": "assistant", "content": "Done"}],
            "output": {"kind": "clean" if clean else "injected", "utility": utility,
                       "attack_success": None if clean else attack}}


def context(tmp_path, mode="improve"):
    paths = {key: tmp_path / key for key in Workspace.__dataclass_fields__}
    for path in paths.values():
        path.mkdir()
    shutil.copytree(TEMPLATE, paths["adapter"], dirs_exist_ok=True)
    material = paths["learning_material"] / "current/tasks"
    material.mkdir(parents=True)
    (material / "train.json").write_text(json.dumps(row("train", True, utility=False)))
    validation = tmp_path / "validation"
    validation.mkdir()
    (validation / "tasks.jsonl").write_text('{"id":"vc"}\n{"id":"vi"}\n')
    calls = []

    def evaluate(task_ids, adapter):
        assert task_ids == ["vc", "vi"]
        candidate = Path(adapter) != paths["adapter"]
        calls.append(candidate)
        rows = [row("vc", True, utility=not (candidate and mode == "clean_regress")),
                row("vi", False, utility=not (candidate and mode == "injected_regress"),
                    attack=not candidate or mode == "tie")]
        if candidate and mode == "error":
            rows[1]["status"] = "error"
        if candidate and mode == "duplicate":
            rows[1]["id"] = "vc"
        return {"results": rows}

    def llm(**kwargs):
        assert "vc" not in kwargs["messages"][-1]["content"]
        path = "artifacts/system_prompt.md"
        if mode == "escape":
            path = "../defense.py"
        if mode == "wrong_owner":
            path = "artifacts/tool_policy.json"
        return {"content": json.dumps({"changes": [], "file_updates": [
            {"path": path, "mode": "append_text", "text": "\nPreserve the authorized task."}]})}

    ctx = StepContext(workspace=Workspace(**paths), access=Access(validation=validation),
                      params={"debugger": "deterministic"}, progress=Progress(1, 1, True),
                      tools={"run_agent": evaluate, "llm": llm,
                             "check_spec": lambda path: check_spec(Path(path), TEMPLATE).to_dict()})
    return ctx, calls


@pytest.mark.parametrize("mode", ["improve", "tie", "clean_regress", "injected_regress", "error", "duplicate", "escape", "wrong_owner"])
def test_candidate_selection_and_parent_preservation(tmp_path, mode):
    ctx, calls = context(tmp_path, mode)
    original = {name: (ctx.workspace.adapter / "artifacts" / name).read_bytes() for name in ARTIFACTS}
    result = SHEEvolver().step(ctx)
    assert result.extra["accepted"] is (mode == "improve"), result.extra
    assert (ctx.workspace.output / "selection.json").is_file()
    if mode != "improve":
        assert original == {name: (ctx.workspace.adapter / "artifacts" / name).read_bytes() for name in ARTIFACTS}
    assert calls == ([] if mode in {"escape", "wrong_owner"} else [False, True])


def test_llm_debugger_routes_to_smallest_owner(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.params["debugger"] = "llm"
    proposal = ctx.tools["llm"]
    count = 0

    def llm(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            assert 'SAFETY_AXES_JSON' not in kwargs['messages'][0]['content']
            assert 'predicted_fix (string)' in kwargs['messages'][0]['content']
            return {"content": json.dumps({"diagnoses": [{"case_id": "train", "primary_owner": "system_prompt",
                "root_cause": "unnecessary refusal", "predicted_fix": "preserve benign utility", "safety_axes": {}}]})}
        return proposal(**kwargs)

    ctx.tools["llm"] = llm
    result = SHEEvolver().step(ctx)
    assert result.extra["accepted"], result.extra
    assert count == 2


def test_no_failures_no_proposal_and_no_validation(tmp_path):
    ctx, calls = context(tmp_path)
    (ctx.workspace.learning_material / "current/tasks/train.json").write_text(json.dumps(row("train", True)))
    ctx.tools["llm"] = lambda **kw: pytest.fail("no failure should require no proposal")
    result = SHEEvolver().step(ctx)
    assert result.status == "done" and not result.extra["accepted"]
    assert not calls


def test_debugger_batches_preserve_every_failed_case(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.params.update(debugger='llm', debugger_batch_size=2)
    tasks = ctx.workspace.learning_material / 'current/tasks'
    for i in range(4):
        (tasks / f'extra-{i}.json').write_text(json.dumps(row(f'extra-{i}', True, utility=False)))
    proposal = ctx.tools['llm']
    seen = []
    def llm(**kwargs):
        payload = json.loads(kwargs['messages'][-1]['content'])
        if 'routes' not in payload:
            return proposal(**kwargs)
        ids = [r['case_id'] for r in payload['routes']]
        assert len(ids) <= 2
        assert {r['case_id'] for r in payload['records']} == set(ids)
        seen.extend(ids)
        return {'content': json.dumps({'diagnoses': [{'case_id': i, 'primary_owner': 'system_prompt',
            'root_cause': 'unnecessary refusal', 'predicted_fix': 'preserve utility', 'safety_axes': {}}
            for i in ids]})}
    ctx.tools['llm'] = llm
    result = SHEEvolver().step(ctx)
    assert result.extra['accepted'], result.extra
    assert sorted(seen) == ['extra-0', 'extra-1', 'extra-2', 'extra-3', 'train']


def test_training_sidecar_and_path_boundary(tmp_path):
    ctx, _ = context(tmp_path)
    root = ctx.workspace.learning_material / "current"
    state = root / "trajectories/train"
    state.mkdir(parents=True)
    (state / "defense-state.json").write_text('{"rule_hits":[{"rule_id":"fixture"}]}')
    record = row("train", True, utility=False)
    record["trajectory"] = "trajectories/train"
    (root / "tasks/train.json").write_text(json.dumps(record))
    assert training_records(ctx.workspace, 1000)[0]["rule_hits"] == [{"rule_id": "fixture"}]
    record["trajectory"] = "../../../../outside"
    (root / "tasks/train.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="escapes"):
        training_records(ctx.workspace, 1000)


@pytest.mark.parametrize("overlap", [True, False])
def test_attribution_requires_observed_pairs(tmp_path, overlap):
    ctx, _ = context(tmp_path)
    assert SHEEvolver().step(ctx).extra["accepted"]
    (ctx.workspace.learning_material / "current/tasks/train.json").write_text(
        json.dumps(row("train" if overlap else "new-training-case", True)))
    output = tmp_path / "second-output"
    scratch = tmp_path / "second-scratch"
    output.mkdir()
    scratch.mkdir()
    ctx = replace(ctx, workspace=replace(ctx.workspace, output=output, scratch=scratch), progress=Progress(2, 2, True))
    assert SHEEvolver().step(ctx).status == "done"
    attribution = json.loads((output / "attribution.json").read_text())
    if overlap:
        assert attribution[0]["actually_fixed"] == ["train"]
    else:
        assert attribution == []


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_cli_envelope_and_usage(tmp_path, monkeypatch, provider):
    from hermit.agent.evolver.base import Usage
    ctx, _ = context(tmp_path)
    ctx.params["proposer"] = provider
    module = "claude_code" if provider == "claude" else "codex"
    used = Usage("fixture", input_tokens=5, output_tokens=2, calls=1)
    monkeypatch.setattr(f"hermit.agent.evolver.methods.evosafe.{module}.call_role",
        lambda *args: ({"content": '{"payload":"{}"}'}, [used], None))
    usage = []
    assert call_model(ctx, [], "she-debugger", usage) == "{}"
    assert usage == [used]


@pytest.mark.parametrize('header', ['', '```json\n', '```json SAFETY_AXES_JSON\n'])
def test_response_object_supports_upstream_fence(header):
    text = '{"diagnoses": []}'
    assert parse_object(header + text + ('\n```' if header else '')) == {'diagnoses': []}


@pytest.mark.parametrize('text', ['[]', 'Refused. {"diagnoses": []}',
                                '```json\n{}\n```\n```json\n{}\n```'])
def test_response_object_rejects_non_object_or_mixed_prose(text):
    with pytest.raises(ValueError):
        parse_object(text)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_debugger_uses_native_structured_schema(tmp_path, monkeypatch, provider):
    ctx, _ = context(tmp_path)
    ctx.params['proposer'] = provider
    module = 'claude_code' if provider == 'claude' else 'codex'
    schema = diagnosis_schema({'train'})
    messages = [{'role': 'user', 'content': 'Diagnose the failed task.'}]

    def role(ctx, received, output_schema, name):
        assert received == messages
        assert output_schema == schema
        entry = output_schema['properties']['diagnoses']['items']
        assert entry['properties']['case_id']['enum'] == ['train']
        assert entry['properties']['predicted_fix'] == {'type': 'string'}
        return {'content': '{"diagnoses": []}'}, [], None

    monkeypatch.setattr(f'hermit.agent.evolver.methods.evosafe.{module}.call_role', role)
    assert call_model(ctx, messages, 'she-debugger', [], schema=schema) == '{"diagnoses": []}'


def test_direct_backend_uses_shared_base_agent(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    ctx, _ = context(tmp_path)
    calls = []

    class Agent:
        def configured(self, **sampling):
            calls.append(sampling)
            return self

        def run(self, messages):
            calls.append(messages)
            return SimpleNamespace(reply='{}', reasoning=None, finish_reason='stop', usage=[])

    ctx = replace(ctx, agent=Agent(), tools={}, params={'proposer': 'direct', 'max_tokens': 123})
    messages = [{'role': 'user', 'content': 'Diagnose the failed task.'}]
    assert call_model(ctx, messages, 'she-debugger', []) == '{}'
    assert calls == [{'max_tokens': 123}, messages]


def test_trainer_end_to_end(tmp_path, monkeypatch):
    import yaml
    from hermit.config import Config
    from hermit.trainer.trainer import Trainer
    from hermit.tools import FunctionTool

    (tmp_path / "pipeline.py").write_text('''
from hermit.task import RunOutput
def run(task, adapter):
    improved = "tested revision" in (adapter / "artifacts/system_prompt.md").read_text()
    clean = not task.get("injection_task_id")
    return RunOutput(output={"kind": "clean" if clean else "injected", "utility": improved,
                     "attack_success": None if clean else not improved}, cost_usd=0.0, tokens=0)
''')
    (tmp_path / "judge.py").write_text("from bridge import score\n")
    rows = [{"id": f"{split}-{kind}", **({"injection_task_id": "fixture"} if kind == "injected" else {})}
            for split in ("train", "val", "test") for kind in ("clean", "injected")]
    (tmp_path / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for split in ("train", "val", "test"):
        (tmp_path / f"{split}.txt").write_text(f"{split}-clean\n{split}-injected\n")
    config = {"data": {"tasks": "tasks.jsonl", "train": "train.txt", "val": "val.txt", "test": "test.txt", "step_size": 2},
              "template": "she@1.0", "agent": {"name": "pipeline.py:run", "concurrency": 1},
              "judge": {"path": "judge.py"},
              "evolver": {"name": "she", "params": {"debugger": "deterministic"}},
              "sandbox": {"enabled": False}, "trainer": {"run_name": "offline", "output_dir": "runs", "epochs": 1}}
    (tmp_path / "run.yaml").write_text(yaml.safe_dump(config))
    original_tools = Trainer._tools

    def tools(self, *args, **kwargs):
        result = original_tools(self, *args, **kwargs)
        def propose(**kwargs):
            assert 'test-clean' not in json.dumps(kwargs)
            return {"content": json.dumps({"changes": [], "file_updates": [{
                "path": "artifacts/system_prompt.md", "mode": "append_text", "text": "\ntested revision\n"}]})}
        result["llm"] = FunctionTool("llm", "offline proposer", propose, source="run")
        return result

    monkeypatch.setattr(Trainer, "_tools", tools)
    trainer = Trainer(Config.load(tmp_path / "run.yaml", []), log=lambda *_: None)
    trainer.train()
    assert "tested revision" in (trainer.ws.adapter / "artifacts/system_prompt.md").read_text()
    report = json.loads((tmp_path / "runs/offline/step_0001/output/selection.json").read_text())
    assert report["accepted"]
    assert report["eval_task_ids"] == ["val-clean", "val-injected"]
    from run_experiment import validate_training
    audit = validate_training(tmp_path / 'runs/offline', method='she')
    assert audit['selection_files'] == 1


def test_native_runtime_final_answer_and_provenance(tmp_path, monkeypatch):
    pytest.importorskip("agentdojo")
    if os.environ.get("HERMIT_TEST_DOCKER") != "1":
        pytest.skip("HERMIT_TEST_DOCKER=1 enables native container integration")
    from agentdojo.agent_pipeline import agent_pipeline as api
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.functions_runtime import FunctionCall
    from agentdojo.types import text_content_block_from_string

    class Reader(BasePipelineElement):
        name = "offline-reader"
        usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0}

        def close(self):
            pass

        def query(self, query, runtime, env, messages=(), extra_args=None):
            if messages[-1]["role"] == "tool":
                message = {"role": "assistant", "content": [text_content_block_from_string("OFFLINE_FINAL_MARKER")], "tool_calls": None}
            else:
                message = {"role": "assistant", "content": None, "tool_calls": [
                    FunctionCall(function="search_product", args={"product_name": "smart watch"}, id="read")]}
            return query, runtime, env, [*messages, message], extra_args or {}

    import victim
    monkeypatch.setattr(victim, "make_victim", lambda *a, **kw: Reader())
    monkeypatch.setattr(api, "get_llm", lambda *a: Reader())
    adapter = tmp_path / "adapter"
    shutil.copytree(TEMPLATE, adapter)
    policy_path = adapter / "artifacts/tool_policy.json"
    policy = json.loads(policy_path.read_text())
    policy["runtime_events"]["detectors"].append({"detector_id": "fixture-final", "hook": "before_response",
        "trigger": {"patterns": ["OFFLINE_FINAL_MARKER"]}, "action": "REPLACE_RESPONSE",
        "safe_response": "Fixture final response", "warning_template": "fixture"})
    policy_path.write_text(json.dumps(policy))
    validate_bundle(adapter)
    case = {"suite": "shopping", "user_task_id": "user_task_0", "injection_task_id": "injection_task_0",
            "injections": {"injection_reviews_0": "OFFLINE_OUTPUT_MARKER"}}
    params = {"model": "gpt-4o-mini-2024-07-18", "logs": "episodes", "hook_runtime": "she"}
    first = run(case, adapter, params=params, base=tmp_path)
    assert first.messages[-1]["content"][0]["content"] == "Fixture final response"
    state = json.loads((first.log / "defense-state.json").read_text())
    assert state["successful_tool_calls"][0]["tool"] == "search_product"
    assert any(e["event"] == "tool_output_processed" for e in state["runtime_execution_events"])
    (adapter / "artifacts/system_prompt.md").write_text("Follow the user's authorized task.")
    second = run(case, adapter, params=params, base=tmp_path)
    assert first.extra["adapter_sha256"] != second.extra["adapter_sha256"]
