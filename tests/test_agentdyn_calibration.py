"""Calibration cannot alter the active root or send injected/test cases to models."""
import json

import yaml

from examples.agentdyn import calibrate_reasoning as calibration


def test_mode_calibration_is_separate_and_training_clean_only(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'trainer': {'output_dir': 'runs', 'run_name': 'source'},
                                    'agent': {'params': {'model': 'same-victim', 'temperature': 0.0}}}))
    source = tmp_path / 'runs/source'
    root = source / 'root'
    root.mkdir(parents=True)
    (root / 'ADAPTER.md').write_text('original defense')
    tasks = source / 'learning_material/current/tasks'
    tasks.mkdir(parents=True)
    for name, injected in [('clean', False), ('injected', True)]:
        row = {'id': name, 'input': {'id': name}, 'status': 'ok',
               'output': {'kind': 'injected' if injected else 'clean', 'utility': True}}
        if injected:
            row['input']['injection_task_id'] = 'frozen'
        (tasks / (name + '.json')).write_text(json.dumps(row))
    calls = []
    def fake(task, adapter, pipeline, judge):
        calls.append(task['id'])
        assert adapter != root and (adapter / 'ADAPTER.md').read_text() == '/no_think\n\noriginal defense'
        assert pipeline.keywords['params']['model'] == 'same-victim'
        assert pipeline.keywords['params']['temperature'] == 0.0
        return {'id': task['id'], 'status': 'ok', 'output': {'utility': True},
                'wall_s': 0, 'tokens': 1, 'log': None, 'error': None}
    monkeypatch.setattr(calibration, 'run_one', fake)
    result = calibration.calibrate(config, tmp_path / 'diagnostic', repeats=3)
    assert calls == ['clean'] * 3
    assert result['calibration']['attempts'] == 3
    assert result['original_training_reference']['attempts'] == 1
    assert (root / 'ADAPTER.md').read_text() == 'original defense'
