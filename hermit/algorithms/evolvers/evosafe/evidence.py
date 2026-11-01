"""Fair, structured evidence: every case keeps its verdict and ordered tool events."""
import json
import re
from pathlib import Path


def clip(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    half = max(1, (limit - 35) // 2)
    return text[:half] + '\n[content omitted for budget]\n' + text[-half:]


def content_text(content):
    if isinstance(content, list):
        text = '\n'.join(str(p.get('content', p.get('text', ''))) for p in content if isinstance(p, dict))
    else:
        text = str(content or '')
    # Provider reasoning consumes the budget and is not needed to diagnose actions.
    return re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()


def summarize_case(row, chars=5000):
    messages = row.get('messages') or []
    events = []
    for message in messages:
        role = message.get('role')
        if role == 'system':
            continue
        event = {'role': role}
        if role == 'tool':
            event['tool'] = (message.get('tool_call') or {}).get('function')
            event['error'] = message.get('error')
        if message.get('tool_calls'):
            event['tool_calls'] = message['tool_calls']
        text = content_text(message.get('content'))
        if text:
            event['content'] = text
        if len(event) > 1:
            events.append(event)
    # Distribute space across events within EACH case. Never truncate serialized JSON
    # or let a long clean trajectory remove all injected/failure evidence.
    allowance = max(120, int(chars) // max(1, len(events)))
    for event in events:
        if 'content' in event:
            original = event['content']
            event['content'] = clip(original, allowance)
            if len(original) > allowance:
                event['content_truncated'] = True
        if event.get('tool_calls'):
            event['tool_calls'] = [
                {'function': c.get('function'), 'args': clip(json.dumps(c.get('args', {})), allowance)}
                for c in event['tool_calls']]
    return {'id': row.get('id'), 'status': row.get('status'), 'output': row.get('output'),
            'judge': row.get('judge'), 'events': events, 'event_count': len(events)}


def training_evidence(workspace, chars=5000):
    return [summarize_case(json.loads(p.read_text()), chars)
            for p in sorted((workspace.learning_material / 'current' / 'tasks').glob('*.json'))]


def audit_evidence(directory, chars=2500):
    """Bounded observable hook actions only; never load environment/judge files."""
    summary = {}
    path = directory / 'audit.json'
    if path.is_file():
        rows = json.loads(path.read_text())
        if not isinstance(rows, list):
            raise ValueError('hook audit must be a list')
        rows = [row for row in rows if isinstance(row, dict)]
        selected = rows if len(rows) <= 12 else rows[:6] + rows[-6:]
        allowance = max(40, int(chars) // max(1, len(selected) * 2))
        events = []
        for row in selected:
            event = {key: row[key] for key in ('tool', 'phase', 'blocked', 'executed', 'output_changed') if key in row}
            for key in ('requested_arguments', 'arguments'):
                if key in row:
                    event[key] = clip(json.dumps(row[key], ensure_ascii=False), allowance)
            events.append(event)
        summary['hooks'] = {'count': len(rows), 'blocked': sum(bool(r.get('blocked')) for r in rows),
                            'outputs_changed': sum(bool(r.get('output_changed')) for r in rows),
                            'omitted_events': len(rows) - len(selected), 'events': events}
    path = directory / 'llm-auditor-calls.jsonl'
    if path.is_file():
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        decisions = [r for r in rows if r.get('event') == 'classification']
        selected = decisions if len(decisions) <= 16 else decisions[:8] + decisions[-8:]
        summary['classifications'] = {'count': len(decisions), 'omitted_events': len(decisions) - len(selected),
            'events': [{key: row[key] for key in ('status', 'has_injected_instruction', 'reason', 'attempt_count', 'output_sha256')
                        if key in row} for row in selected]}
    return summary


def result_evidence(rows, chars=5000):
    evidence = []
    for row in rows:
        enriched = dict(row)
        # Hermit only returns log paths for TRAIN runs. Do not discover validation
        # or test logs by scanning the filesystem.
        audit = {}
        if row.get('log'):
            path = Path(row['log'])
            directory = path if path.is_dir() else path.parent
            path = directory / 'trajectory.json' if path.is_dir() else path
            if path.is_file():
                enriched['messages'] = json.loads(path.read_text())
            audit = audit_evidence(directory, max(500, int(chars) // 2))
        item = summarize_case(enriched, chars)
        if audit:
            item['audit'] = audit
        evidence.append(item)
    return evidence
