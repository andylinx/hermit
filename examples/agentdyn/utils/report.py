"""Report grouped security metrics from Hermit eval results.jsonl."""
import argparse
from collections import Counter
import json
from pathlib import Path

from hermit.agent.evolver.methods.evosafe.contract import aggregate


def summarize(rows, expected_ids, repeats=1):
    if repeats < 1 or not expected_ids or len(set(expected_ids)) != len(expected_ids):
        raise ValueError("provide unique expected IDs and positive repeats")
    valid = [r for r in rows if r.get("status") == "ok"]
    errors = len(rows) - len(valid)
    expected = Counter((task, repeat) for task in expected_ids for repeat in range(1, repeats + 1))
    observed = Counter((r["id"], r.get("repeat", 1)) for r in rows)
    coverage_ok = observed == expected
    report = {"episodes": len(rows), "errors": errors, "error_rate": errors / len(rows) if rows else None,
              "expected_episodes": sum(expected.values()), "coverage_ok": coverage_ok,
              "complete": coverage_ok and errors == 0,
              "unknown_cost_episodes": sum(r.get("cost_usd") is None for r in rows)}
    try:
        report["completed_episode_metrics"] = aggregate(valid)
    except ValueError as exc:
        report["metrics_error"] = str(exc)
    # Partial-run metrics are diagnostic only, never a candidate selection score.
    report["selection_objective"] = report.get("completed_episode_metrics", {}).get("objective") if report["complete"] else None
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--split", type=Path, required=True, help="expected test IDs, one per line")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    ids = [s.strip() for s in args.split.read_text().splitlines() if s.strip() and not s.startswith("#")]
    print(json.dumps(summarize([json.loads(s) for s in args.results.read_text().splitlines() if s.strip()], ids, args.repeats), indent=2))
