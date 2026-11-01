"""Offline terminal-protocol audit; preserves all original verdicts and artifacts."""
import argparse
import json
from pathlib import Path

from hermit.integrations.openai_victim import terminal_protocol_error


def audit(source):
    rows = []
    for path in sorted(Path(source).glob('*.json')):
        row = json.loads(path.read_text())
        if 'status' not in row or 'id' not in row:
            continue
        terminal = (row.get('messages') or [{}])[-1]
        problem = None
        if row['status'] == 'ok':
            problem = ('missing_terminal_assistant' if terminal.get('role') != 'assistant' else
                       terminal_protocol_error(terminal.get('content'), bool(terminal.get('tool_calls'))))
        rows.append({'id': row['id'], 'original_status': row['status'],
                     'original_output': row.get('output'), 'protocol_error': problem,
                     'effective_status': 'error' if problem else row['status']})
    return {'scope': 'offline validation sidecar, no new model calls; original verdicts unchanged',
            'cases': len(rows), 'original_errors': sum(r['original_status'] != 'ok' for r in rows),
            'additional_protocol_errors': sum(bool(r['protocol_error']) for r in rows), 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(args.source)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
