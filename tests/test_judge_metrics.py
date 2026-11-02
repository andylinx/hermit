"""Multi-metric judges: per-episode metrics, the optional task aggregate, and the Claude Code role backend."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermit.task import JudgeResult, RunOutput, load_aggregate, normalise_judge, summarise
from hermit.trainer.rollout import run_tasks


def test_normalise_judge_keeps_metrics_apart_from_extra():
    verdict = normalise_judge({"score": 1, "feedback": "f", "metrics": {"utility": True}, "note": 2})
    assert verdict.metrics == {"utility": True} and verdict.extra == {"note": 2}
    assert normalise_judge(0.5).metrics == {}


def test_summarise_without_aggregate_and_on_failure():
    assert summarise([{"id": "a"}], None) is None
    assert summarise([], lambda rows: 1 / 0)["error"].startswith("ZeroDivisionError")
    assert summarise([], lambda rows: [1])["error"].startswith("TypeError")


def test_load_aggregate_from_judge_file(tmp_path):
    (tmp_path / "judge.py").write_text("def score(t, o):\n    return 1.0\n"
                                       "def total(rows):\n    return {'n': len(rows)}\n")
    assert load_aggregate({"path": "judge.py", "aggregate": None}, tmp_path) is None
    fn = load_aggregate({"path": "judge.py", "aggregate": "total"}, tmp_path)
    assert fn([{}, {}]) == {"n": 2}


def test_aggregate_sees_failed_runs_with_their_status():
    def pipeline(task, adapter):
        if task["id"] == "bad":
            raise RuntimeError("no terminal answer")
        return RunOutput(output={"ok": True})

    def judge(task, out):
        return JudgeResult(1.0, metrics={"utility": True})

    rows = run_tasks([{"id": "good"}, {"id": "bad"}], None, pipeline, judge, concurrency=1)
    assert rows[1]["judge"]["metrics"] == {} and rows[1]["status"] == "error"
    seen = summarise(rows, lambda rs: {"statuses": [r["status"] for r in rs],
                                       "utility": [r["judge"]["metrics"].get("utility") for r in rs]})
    assert seen == {"statuses": ["ok", "error"], "utility": [True, None]}


def record(kind, utility, attack=None, status="ok"):
    task = {"id": f"{kind}-{utility}-{attack}-{status}", **({"injection_task_id": "goal"} if kind == "injected" else {})}
    metrics = {} if status != "ok" else {"kind": kind, "utility": utility, "attack_success": attack}
    return {"id": task["id"], "input": task, "status": status, "judge": {"score": 0.0, "metrics": metrics}}


def test_agentdyn_summary_counts_errors_and_withholds_partial_objective():
    from hermit.integrations.agentdyn import summary
    rows = [record("clean", True), record("clean", False), record("injected", True, False),
            record("injected", False, True)]
    full = summary(rows)
    assert full["clean_utility_completed"] == 0.5 and full["asr_completed"] == 0.5 and full["objective"] == 0.0
    assert full["secure_completions"] == 1
    partial = summary(rows + [record("injected", False, None, status="error")])
    assert partial["errors_injected"] == 1 and partial["n_injected"] == 3 and partial["objective"] is None
    assert partial["asr_completed"] == 0.5


def role_ctx(tmp_path, **params):
    scratch, output = tmp_path / "scratch", tmp_path / "output"
    scratch.mkdir()
    output.mkdir()
    return SimpleNamespace(workspace=SimpleNamespace(scratch=scratch, output=output),
                           params=params, sandbox=None, cancel=None)


def fake_claude(event, check=None):
    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            if check:
                check(command, kwargs["stdin"].read())
            kwargs["stdout"].write(json.dumps(event))

        def poll(self):
            return self.returncode
    return Process


def test_claude_role_has_no_tools_and_returns_structured_output(tmp_path, monkeypatch):
    from hermit.algorithms.evolvers.evosafe import claude_code
    answer = {"approved": True, "summary": "ok"}

    def check(command, stdin):
        assert command[:2] == ["claude", "-p"] and command[command.index("--tools") + 1] == ""
        assert "--no-session-persistence" in command
        assert command[command.index("--append-system-prompt") + 1] == "ROLE: Criticizer."
        assert json.loads(command[command.index("--json-schema") + 1])["required"] == ["approved"]
        assert "evidence" in stdin and "ROLE" not in stdin

    monkeypatch.setattr(claude_code.subprocess, "Popen", fake_claude(
        {"type": "result", "is_error": False, "structured_output": answer, "num_turns": 1,
         "usage": {"input_tokens": 7, "output_tokens": 3}}, check))
    response, usage, error = claude_code.call_role(
        role_ctx(tmp_path), [{"role": "system", "content": "ROLE: Criticizer."}, {"role": "user", "content": "evidence"}],
        {"type": "object", "required": ["approved"]}, "trial-001-criticizer")
    assert error is None and json.loads(response["content"]) == answer
    assert usage[0].input_tokens == 7 and usage[0].output_tokens == 3


@pytest.mark.parametrize("event, expected", [
    ({"type": "result", "stop_reason": "refusal", "is_error": False}, "SAFETY_REVIEW_REFUSAL"),
    ({"type": "result", "is_error": True, "subtype": "error_max_turns"}, "Claude Code failed"),
])
def test_claude_role_reports_refusal_and_failure(tmp_path, monkeypatch, event, expected):
    from hermit.algorithms.evolvers.evosafe import claude_code
    monkeypatch.setattr(claude_code.subprocess, "Popen", fake_claude(event))
    response, _, error = claude_code.call_role(role_ctx(tmp_path), [{"role": "user", "content": "x"}],
                                              {"type": "object"}, "trial-001-designer")
    assert response is None and error.startswith(expected)
