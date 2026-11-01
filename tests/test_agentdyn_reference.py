"""Frozen reference reuse never hides failures or substitutes for changed defenses."""
import json

import pytest
import yaml

from examples.agentdyn import replay_reference as replay
from hermit.task import RunOutput


def setup_reference(tmp_path):
    source = tmp_path / 'source'
    root = source / 'root'
    root.mkdir(parents=True)
    (root / 'ADAPTER.md').write_text('root')
    (root / 'defense.py').write_text('identity')
    params = {'model': 'frozen-model', 'temperature': 0.0, 'logs': 'old-logs'}
    (source / 'config.yaml').write_text(yaml.safe_dump({'agent': {'params': params}}))
    current = source / 'learning_material/current'
    (current / 'tasks').mkdir(parents=True)
    for name, status in [('good', 'ok'), ('failed', 'error')]:
        log = current / 'trajectories' / name
        log.mkdir(parents=True)
        (log / 'trajectory.json').write_text('[]')
        row = {'id': name, 'input': {'id': name}, 'status': status,
               'output': {'utility': True, 'kind': 'clean', 'attack_success': None} if status == 'ok' else None,
               'pipeline_extra': {'adapter_sha256': replay.adapter_digest(root)},
               'trajectory': 'trajectories/' + name, 'tokens': 123, 'messages': []}
        (current / 'tasks' / (name + '.json')).write_text(json.dumps(row))
    snapshot = tmp_path / 'reference.json'
    info = replay.freeze(source, snapshot)
    assert info['cases'] == 2 and info['errors'] == 1
    return root, {**params, 'logs': 'new-logs', 'reference_snapshot': str(snapshot)}


def test_reference_reuses_known_measurements_without_remetering(tmp_path, monkeypatch):
    root, params = setup_reference(tmp_path)
    monkeypatch.setattr(replay, 'native_run', lambda *a, **k: pytest.fail('unexpected fresh call'))
    output = replay.run({'id': 'good'}, root, params=params, base=tmp_path)
    assert output.tokens == 0 and output.cost_usd == 0
    assert output.extra['reference_replay']['original_tokens'] == 123
    with pytest.raises(replay.ReferenceFailure) as error:
        replay.run({'id': 'failed'}, root, params=params, base=tmp_path)
    assert error.value.tokens == 0 and error.value.log.is_dir()


def test_reference_checks_provider_and_case_and_bypasses_changed_defense(tmp_path, monkeypatch):
    root, params = setup_reference(tmp_path)
    with pytest.raises(ValueError, match='settings mismatch'):
        replay.run({'id': 'good'}, root, params={**params, 'temperature': 0.6}, base=tmp_path)
    with pytest.raises(ValueError, match='case mismatch'):
        replay.run({'id': 'good', 'changed': True}, root, params=params, base=tmp_path)
    calls = []
    def native(task, adapter, **kwargs):
        calls.append(task['id'])
        return RunOutput(output={'fresh': True})
    monkeypatch.setattr(replay, 'native_run', native)
    assert replay.run({'id': 'not-in-training-reference'}, root, params=params, base=tmp_path).output['fresh']
    (root / 'ADAPTER.md').write_text('changed defense')
    assert replay.run({'id': 'good'}, root, params=params, base=tmp_path).output['fresh']
    assert calls == ['not-in-training-reference', 'good']
