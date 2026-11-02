import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('agentdyn_compare',Path(__file__).resolve().parents[1]/'examples/agentdyn/utils/compare.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_report_rejects_missing_and_separates_goal_namespaces():
    tasks=[{'id':'a','suite':'shopping','user_task_id':'user_task_0'},
           {'id':'b','suite':'shopping','user_task_id':'user_task_0','injection_task_id':'injection_task_0'},
           {'id':'c','suite':'github','user_task_id':'user_task_0','injection_task_id':'injection_task_0'}]
    rows=[{'id':'a','status':'ok','output':{'kind':'clean','utility':True,'attack_success':None}},
          {'id':'b','status':'ok','output':{'kind':'injected','utility':True,'attack_success':False}},
          {'id':'c','status':'error','output':None}]
    report=module.compare(tasks,['a','b','c'],{'baseline':rows})['runs']['baseline']
    assert not report['complete']
    assert report['overall']['objective'] is None
    assert report['overall']['errors']==1
    assert set(report['by_injection_goal'])=={'shopping/injection_task_0','github/injection_task_0'}
    assert report['overall']['secure_task_completion']['successes']==1
    with pytest.raises(ValueError,match='missing'):
        module.compare(tasks,['a','b','c'],{'baseline':rows[:2]})


def test_failed_episode_usage_counts_towards_budget(tmp_path):
    from hermit.trainer.rollout import run_tasks
    from hermit.trainer.budget import Budget
    class Failure(RuntimeError):
        tokens=123
        cost_usd=0.25
        log=tmp_path
    def pipeline(task, adapter):
        raise Failure('sanitized failure')
    budget=Budget()
    rows=run_tasks([{'id':'one'}],None,pipeline,lambda *args: None,concurrency=1,budget=budget)
    assert rows[0]['status']=='error' and rows[0]['tokens']==123
    assert rows[0]['log']==str(tmp_path)
    assert budget.snapshot()['tokens']['rollout']==123
    assert budget.snapshot()['usd']['rollout']==0.25
