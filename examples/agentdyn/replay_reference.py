"""Reuse an explicitly frozen TRAIN reference; changed defenses always run natively.

This avoids paying for another identical baseline while debugging search control
flow. It preserves failed reference episodes, checks case/adapter/provider settings,
and charges zero NEW API tokens for a replay. It never supplies test outcomes.
"""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import yaml
from hermit.integrations.agentdyn import run as native_run
from hermit.task import RunOutput


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def adapter_digest(adapter):
    h = hashlib.sha256()
    for name in ('ADAPTER.md', 'defense.py'):
        h.update(name.encode() + (Path(adapter) / name).read_bytes())
    return h.hexdigest()


def settings_digest(params):
    return digest({k: v for k, v in params.items() if k not in ('logs', 'reference_snapshot')})


def freeze(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    config = yaml.safe_load((source / 'config.yaml').read_text())
    config = config.get('config', config)
    material = (source / 'learning_material/current').resolve()
    adapter_hash = adapter_digest(source / 'root')
    rows = []
    for path in sorted((material / 'tasks').glob('*.json')):
        row = json.loads(path.read_text())
        if row['id'] != row['input']['id']:
            raise ValueError('reference row/input ID mismatch')
        if row['status'] == 'ok' and row['pipeline_extra']['adapter_sha256'] != adapter_hash:
            raise ValueError('reference material was not evaluated with the root')
        relative = Path(row['trajectory'])
        log = (material / relative).resolve()
        if relative.is_absolute() or not log.is_relative_to(material / 'trajectories') or not log.is_dir():
            raise ValueError('invalid training trajectory provenance')
        rows.append({**row, 'log': str(log), 'case_sha256': digest(row['input'])})
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('reference must contain unique training cases')
    snapshot = {'scope': 'recorded TRAIN reference; errors retained; not fresh API evaluation',
                'source': str(source), 'adapter_sha256': adapter_hash,
                'params_sha256': settings_digest(config['agent']['params']), 'rows': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(snapshot, stream)
    return {'cases': len(rows), 'errors': sum(r['status'] != 'ok' for r in rows),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


@lru_cache(maxsize=4)
def load(path):
    path = Path(path)
    snapshot = json.loads(path.read_text())
    return snapshot, {r['id']: r for r in snapshot['rows']}, hashlib.sha256(path.read_bytes()).hexdigest()


class ReferenceFailure(RuntimeError):
    tokens = 0
    cost_usd = 0.0

    def __init__(self, log):
        super().__init__('recorded reference execution failed; original failure retained')
        self.log = Path(log)


def run(task, adapter, *, params, base):
    reference = params.get('reference_snapshot')
    if not reference:
        return native_run(task, adapter, params=params, base=base)
    snapshot, index, snapshot_hash = load(str((Path(base) / reference).resolve()))
    if settings_digest(params) != snapshot['params_sha256']:
        raise ValueError('reference victim/settings mismatch; cannot reuse measurement')
    row = index.get(task['id'])
    if row is None or adapter is None or adapter_digest(adapter) != snapshot['adapter_sha256']:
        return native_run(task, adapter, params=params, base=base)
    if digest(task) != row['case_sha256']:
        raise ValueError('reference case mismatch; cannot reuse measurement')
    if row['status'] != 'ok':
        raise ReferenceFailure(row['log'])
    extra = {**row['pipeline_extra'], 'reference_replay': {'snapshot_sha256': snapshot_hash,
             'source': snapshot['source'], 'original_tokens': row.get('tokens'), 'new_api_tokens': 0}}
    return RunOutput(output=row['output'], log=Path(row['log']), messages=row.get('messages'),
                     tokens=0, cost_usd=0.0, wall_s=0.0, extra=extra)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze(args.source, args.output), indent=2))
