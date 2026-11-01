"""TRAIN-clean-only reasoning-mode diagnostic; never changes an active search.

Tests the documented /no_think system switch with the same victim, root defense,
tools and decoding settings. Repeats are reported separately; no ASR claims.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import json
from pathlib import Path
import shutil
import time

import yaml
from hermit.integrations.agentdyn import run, score
from hermit.trainer.rollout import run_one


def calibrate(config, output, repeats=3, profile='off'):
    config, output = Path(config).resolve(), Path(output).resolve()
    if repeats < 1:
        raise ValueError('positive repeats required')
    if profile not in ('off', 'recommended'):
        raise ValueError('profile must be off or recommended')
    data = yaml.safe_load(config.read_text())
    base = config.parent
    source = base / data['trainer']['output_dir'] / data['trainer']['run_name']
    recorded = [json.loads(p.read_text()) for p in (source / 'learning_material/current/tasks').glob('*.json')]
    clean = [r for r in recorded if not r['input'].get('injection_task_id')]
    if not clean:
        raise ValueError('requires completed training material, not test data')
    output.mkdir(parents=True, exist_ok=False)
    adapter = output / 'adapter'
    shutil.copytree(source / 'root', adapter)
    prompt = adapter / 'ADAPTER.md'
    if profile == 'off':
        prompt.write_text('/no_think\n\n' + prompt.read_text())
    params = dict(data['agent']['params'])
    if profile == 'recommended':
        params.update(temperature=0.6, top_p=0.95)
    params['logs'] = str(output / 'episodes')
    pipeline = functools.partial(run, params=params, base=base)
    plan = {'scope': 'training clean only; model-mode diagnostic, not a defense improvement',
            'profile': profile,
            'intervention': '/no_think prepended to root ADAPTER.md' if profile == 'off'
                            else 'unchanged root prompt; temperature 0.6, top_p 0.95',
            'same_model': params['model'], 'temperature': params['temperature'],
            'case_ids': [r['id'] for r in clean], 'repeats': repeats,
            'original_reference_repeats': 1,
            'source': str(source), 'source_documentation':
            'https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5'}
    (output / 'protocol.json').write_text(json.dumps(plan, indent=2))
    rows = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool, (output / 'results.jsonl').open('w') as stream:
        jobs = {pool.submit(run_one, row['input'], adapter, pipeline, score): repeat
                for repeat in range(1, repeats + 1) for row in clean}
        for future in as_completed(jobs):
            result = future.result()
            item = {k: result[k] for k in ('id', 'status', 'output', 'wall_s', 'tokens', 'log', 'error')}
            item['repeat'] = jobs[future]
            rows.append(item)
            stream.write(json.dumps(item) + '\n')
            stream.flush()
    def counts(items):
        valid = [r for r in items if r['status'] == 'ok']
        return {'attempts': len(items), 'errors': len(items)-len(valid),
                'utility_successes': sum(bool(r['output']['utility']) for r in valid),
                'completed': len(valid)}
    summary = {'scope': plan['scope'], 'original_training_reference': counts(clean),
               'profile': profile, 'calibration': counts(rows), 'by_repeat': {str(i): counts([r for r in rows if r['repeat'] == i])
               for i in range(1, repeats+1)}, 'wall_s': time.monotonic()-started,
               'recorded_tokens': sum(r['tokens'] or 0 for r in rows)}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--profile', choices=['off', 'recommended'], default='off')
    args = parser.parse_args()
    print(json.dumps(calibrate(args.config, args.output, args.repeats, args.profile), indent=2))
