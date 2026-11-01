"""Compare complete fixed-case evaluations without feeding test results into search."""
import argparse
from collections import Counter
import json
from pathlib import Path


def load(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def metrics(rows):
    valid = [r for r in rows if r['status'] == 'ok']
    clean = [r for r in valid if r['output']['kind'] == 'clean']
    injected = [r for r in valid if r['output']['kind'] == 'injected']
    def rate(group, field):
        return {'successes': sum(r['output'][field] for r in group), 'n': len(group),
                'rate': sum(r['output'][field] for r in group) / len(group) if group else None}
    cu, attack, iu = rate(clean, 'utility'), rate(injected, 'attack_success'), rate(injected, 'utility')
    joint = {'successes': sum(r['output']['utility'] and not r['output']['attack_success'] for r in injected),
             'n': len(injected)}
    joint['rate'] = joint['successes'] / joint['n'] if joint['n'] else None
    return {'episodes': len(rows), 'errors': len(rows)-len(valid), 'clean_utility': cu,
            'asr': attack, 'injected_utility': iu, 'secure_task_completion': joint,
            'objective': cu['rate']-attack['rate'] if clean and injected and len(valid)==len(rows) else None}


def compare(tasks, ids, runs, repeats=1):
    if not ids or len(ids)!=len(set(ids)) or repeats<1:
        raise ValueError('unique nonempty split and positive repeats required')
    index = {t['id']: t for t in tasks}
    if not set(ids) <= index.keys():
        raise ValueError('split refers to unknown tasks')
    expected = Counter((i,r) for i in ids for r in range(1,repeats+1))
    result = {}
    for name, rows in runs.items():
        observed = Counter((r['id'],r.get('repeat',1)) for r in rows)
        if observed != expected:
            raise ValueError(f'{name}: missing, duplicate or unexpected episodes')
        all_metrics = metrics(rows)
        result[name] = {'complete': all_metrics['errors']==0, 'overall': all_metrics,
            'by_suite': {s: metrics([r for r in rows if index[r['id']]['suite']==s])
                         for s in sorted({index[i]['suite'] for i in ids})},
            'by_injection_goal': {suite + '/' + goal: metrics([r for r in rows if
                index[r['id']]['suite']==suite and index[r['id']].get('injection_task_id')==goal])
                for suite,goal in sorted({(index[i]['suite'],index[i]['injection_task_id']) for i in ids if index[i].get('injection_task_id')})},
            'tokens': sum(r.get('tokens') or 0 for r in rows),
            'unknown_token_episodes': sum(r.get('tokens') is None for r in rows)}
    return {'protocol': 'fixed-case descriptive comparison; no statistical significance claim',
            'task_groups': len({(index[i]['suite'],index[i]['user_task_id']) for i in ids}),
            'repeats': repeats, 'runs': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',type=Path,required=True)
    parser.add_argument('--split',type=Path,required=True)
    parser.add_argument('--run',action='append',required=True,help='LABEL=results.jsonl')
    parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    runs={}
    for entry in args.run:
        name,sep,path=entry.partition('=')
        if not sep or name in runs: raise ValueError('provide unique LABEL=path')
        runs[name]=load(path)
    result=compare(load(args.tasks),[s for s in args.split.read_text().splitlines() if s and not s.startswith('#')],runs,args.repeats)
    text=json.dumps(result,indent=2)
    if args.output: args.output.write_text(text+'\n')
    print(text)
