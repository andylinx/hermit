"""Build paired failure dossiers from a recorded TRAIN search; optionally re-analyze.

Does not generate candidates, run attacks, read test logs or change recorded results.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

from hermit.agent.evolver.methods.evosafe.evidence import failure_packet, result_evidence
from hermit.agent.evolver.methods.evosafe.roles import (
    ANALYZER, ANALYSIS_SCHEMA, EDITABLE, invoke_role, measured_comparison,
)
from hermit.agent.base.records import parse_log


def debug(source, output, analyze=False, resume=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=resume)
    scratch = output / 'scratch'
    scratch.mkdir(exist_ok=resume)
    ctx = SimpleNamespace(workspace=SimpleNamespace(output=output, scratch=scratch),
                          params={'proposer': 'codex', 'codex_timeout_s': 600},
                          sandbox=None, cancel=None)
    recorded = source / 'workspace/output'
    if any(t.get('promoted') for t in json.loads((recorded / 'selection.json').read_text())['trials']):
        raise ValueError('this diagnostic requires a fixed unpromoted parent')
    parent = json.loads((recorded / 'parent-results.json').read_text())
    tasks = {}
    for path in (source / 'learning_material/current/tasks').glob('*.json'):
        row = json.loads(path.read_text())
        tasks[row['id']] = row['input']
    report = json.loads((output / 'report.json').read_text()) if resume and (output / 'report.json').exists() else {}
    usage = json.loads((output / 'usage.json').read_text()) if resume and (output / 'usage.json').exists() else []
    for result in sorted(recorded.glob('trial-*-results.json')):
        stem = result.name.removesuffix('-results.json')
        if resume and stem in report and (not analyze or 'analysis' in report[stem]):
            continue
        rows = json.loads(result.read_text())
        if not {r['id'] for r in rows + parent} <= tasks.keys():
            raise ValueError('diagnostic evidence must belong to recorded training material')
        packet = failure_packet(parent, rows, tasks)
        counts = measured_comparison(parent, rows)
        candidate = recorded / (stem + '-candidate')
        if candidate.is_dir():
            candidate_files = {name: (candidate / name).read_text() for name in EDITABLE}
        else:
            # Earlier integration skipped candidate archival on runtime failure.
            messages = json.loads((recorded / (stem + '-analyzer-input.json')).read_text())
            candidate_files = json.loads(messages[-1]['content'])['candidate_files']
        payload = {'priority_cases': packet, 'measured_comparison': counts,
                   'parent_files': {name: (source / 'root' / name).read_text() for name in EDITABLE},
                   'candidate_files': candidate_files,
                   'candidate_outcomes': result_evidence(rows),
                   'parent_outcomes': result_evidence(parent),
                   'instruction': 'Diagnose only this recorded trial. Use supplied counts exactly; '
                   'do not invent unevaluated cases or prescribe attack payloads.'}
        (output / (stem + '-paired-evidence.json')).write_text(json.dumps(payload, indent=2))
        report[stem] = {'measured_comparison': counts, 'case_index': packet['case_index']}
        if analyze:
            saved = output / (stem + '-reanalyzer.json')
            report[stem]['analysis'] = json.loads(saved.read_text()) if resume and saved.exists() else invoke_role(
                ctx, ANALYZER, payload, ANALYSIS_SCHEMA, stem + '-reanalyzer', usage)
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    usage = []
    for event_log in sorted(output.glob('codex-*-events.jsonl')):
        _, events = parse_log(event_log, 'codex', 'codex')
        usage.extend(asdict(e) for e in events)
    (output / 'usage.json').write_text(json.dumps(usage, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--analyze', action='store_true', help='run fresh Codex Analyzer sessions')
    parser.add_argument('--resume', action='store_true', help='reuse completed diagnostic analyses')
    args = parser.parse_args()
    report = debug(args.source, args.output, args.analyze, args.resume)
    print(json.dumps({name: row['measured_comparison'] for name, row in report.items()}, indent=2))
