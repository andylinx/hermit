"""Multi-metric judges: per-episode metrics and the optional task aggregate."""
import pytest

from hermit.task import JudgeResult, RunOutput, load_aggregate, normalise_judge, summarise
from hermit.trainer.rollout import run_tasks


@pytest.mark.parametrize("value,score,feedback,extra", [
    (-3.5, -3.5, "", {}),
    ({"score": 7.5, "feedback": "legacy", "f1": 0.75}, 7.5, "legacy", {"f1": 0.75}),
    # The third positional argument must remain extra, not metrics.
    (JudgeResult(0.5, "legacy", {"f1": 0.75}), 0.5, "legacy", {"f1": 0.75}),
], ids=["number", "dict", "result-positional"])
def test_legacy_single_score_judges(value, score, feedback, extra):
    verdict = normalise_judge(value)
    assert (verdict.score, verdict.feedback, verdict.extra) == (score, feedback, extra)
    assert verdict.metrics == {}


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
    assert load_aggregate({"path": "judge.py"}, tmp_path) is None
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
