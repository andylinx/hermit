"""Coverage and split guarantees for expanded fixed replay preparation."""
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("prepare_expanded", Path(__file__).parents[1] / "examples/agentdyn/prepare_expanded.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture_cases():
    cases = {}
    for suite in module.SUITES:
        for task in range(20):
            for goal in range(4):
                row = {"suite": suite, "user_task_id": f"user_task_{task}",
                       "injection_task_id": f"injection_task_{goal}", "injections": {"vector": "inert fixture"}}
                cases[module.digest(row)] = row
    return cases


def test_group_split_coverage_and_determinism():
    cases = fixture_cases()
    audit = {key: {"eligible": True} for key in cases}
    rows, splits, assignments, selected = module.select(cases, audit)
    assert len(rows) == 54 and {len(ids) for ids in splits.values()} == {18}
    assert len(selected) == 36 and len(set(selected)) == 36
    assert len({(a["suite"], a["user_task_id"]) for a in assignments}) == 18
    by_id = {r["id"]: r for r in rows}
    owners = {}
    for split, ids in splits.items():
        assert {by_id[i]["suite"] for i in ids[:6]} == set(module.SUITES)
        assert sum("injection_task_id" not in by_id[i] for i in ids[:6]) == 3
        for case_id in ids:
            r = by_id[case_id]; group = (r["suite"], r["user_task_id"])
            assert group not in module.EXCLUSIONS
            assert owners.setdefault(group, split) == split
    reordered = dict(reversed(list(cases.items())))
    assert module.select(reordered, audit) == (rows, splits, assignments, selected)


def test_failed_native_checks_cannot_enter_selection():
    cases = fixture_cases()
    audit = {key: {"eligible": case["suite"] != "github"} for key, case in cases.items()}
    with pytest.raises(ValueError, match="github"):
        module.select(cases, audit)


def test_source_whitelist_discards_model_answers_and_scores(tmp_path):
    for suite in module.SUITES:
        directory = tmp_path / suite
        directory.mkdir()
        record = {"suite_name": suite, "user_task_id": "user_task_0",
                  "injection_task_id": "injection_task_0", "injections": {"vector": "inert fixture"},
                  "messages": ["SECRET_OLD_ANSWER"], "utility": True, "attack_success": True}
        (directory / "record.json").write_text(json.dumps(record))
    cases, sources = module.read_collection(tmp_path)
    assert len(cases) == 3
    assert "SECRET_OLD_ANSWER" not in json.dumps(cases)
    assert all(set(c) == {"suite", "user_task_id", "injection_task_id", "injections"} for c in cases.values())
    assert all(len(items[0]["file_sha256"]) == 64 for items in sources.values())


def test_native_three_suite_initialization():
    pytest.importorskip("agentdojo")
    from agentdojo.task_suite import get_suite
    cases = {}
    for suite in module.SUITES:
        s = get_suite("v1.2.2", suite)
        vector, content = next(iter(s.get_injection_vector_defaults().items()))
        row = {"suite": suite, "user_task_id": "user_task_0", "injection_task_id": "injection_task_1" if suite == "github" else "injection_task_0",
               "injections": {vector: content}}
        cases[module.digest(row)] = row
    inventory, audit = module.audit_native(cases)
    assert set(inventory) == set(module.SUITES)
    assert all(a["eligible"] for a in audit.values())
    assert all(a["initial_clean_utility"] is False for a in audit.values())


def test_full_inventory_preserves_acceptance_split_ownership(tmp_path):
    cases = fixture_cases()
    audit = {key: {"eligible": True} for key in cases}
    rows, splits, assignments, selected = module.select(cases, audit)
    report = module.export_full(tmp_path / "full", cases, audit, assignments, 20261101)
    owners = {(g["suite"], g["user_task_id"]): g["split"] for g in report["groups"]}
    assert len(owners) == 55
    assert all(owners[(g["suite"], g["user_task_id"])] == g["split"] for g in assignments)
    assert sum(report["counts"].values()) == 55 * 5
    all_ids = set()
    for split in ("train", "val", "test"):
        ids = set((tmp_path / "full" / f"{split}.txt").read_text().splitlines())
        assert all_ids.isdisjoint(ids)
        all_ids.update(ids)
        assert set(splits[split]) <= ids


def test_thirty_case_extension_retains_all_old_split_ownership(tmp_path):
    from examples.agentdyn.prepare_thirty import prepare
    cases = fixture_cases()
    audit = {key: {'eligible': True} for key in cases}
    rows, splits, assignments, _ = module.select(cases, audit)
    source = tmp_path / 'old'
    source.mkdir()
    for name, ids in splits.items():
        (source / f'{name}.txt').write_text('\n'.join(ids) + '\n')
    full = module.export_full(source / 'full', cases, audit, assignments, 20261101)
    first = prepare(source, tmp_path / 'new')
    second = prepare(source, tmp_path / 'again')
    assert first['tasks_sha256'] == second['tasks_sha256']
    assert first['counts'] == {'train': 30, 'val': 30, 'test': 30}
    owners = {(r['suite'], r['user_task_id']): r['split'] for r in full['groups']}
    assert all(owners[(r['suite'], r['user_task_id'])] == r['split'] for r in first['groups'])
    for name, ids in splits.items():
        assert set(ids) <= set((tmp_path / 'new' / f'{name}.txt').read_text().splitlines())
