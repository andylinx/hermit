"""Select a fixed six-episode connectivity experiment from already-frozen cases.

Selection is fixed before each run. Revision 2 excludes user tasks 4 and 19,
whose prompt and judge disagree at the pinned revision. These small groups are
for integration debugging, not a statistically meaningful AgentDyn score.
"""
import argparse
import hashlib
import json
from pathlib import Path

from hermit.integrations.agentdyn import validate_case

GROUPS = {"train": "user_task_0", "val": "user_task_3", "test": "user_task_2"}


def prepare(source, output):
    source, output = Path(source), Path(output)
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    selected = []
    splits = {}
    for split, task in GROUPS.items():
        injected = [r for r in rows if r.get("suite") == "shopping" and r.get("user_task_id") == task
                    and r.get("injection_task_id") == "injection_task_2"]
        if len(injected) != 1:
            raise ValueError(f"expected exactly one frozen injection_task_2 case for {task}")
        clean = {"id": f"{task}-clean", "suite": "shopping", "user_task_id": task}
        case = {k: injected[0][k] for k in ("suite", "user_task_id", "injection_task_id", "injections")}
        case["id"] = f"{task}-injected"
        validate_case(case)
        selected.extend([clean, case])
        splits[split] = [clean["id"], case["id"]]
    output.mkdir(parents=True, exist_ok=False)
    (output / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in selected))
    for split, ids in splits.items():
        (output / f"{split}.txt").write_text("\n".join(ids) + "\n")
    (output / "manifest.json").write_text(json.dumps({
        "protocol": "six-episode integration smoke revision 2, not official benchmark results", "groups": GROUPS,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "tasks_sha256": hashlib.sha256((output / "tasks.jsonl").read_bytes()).hexdigest()}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)
