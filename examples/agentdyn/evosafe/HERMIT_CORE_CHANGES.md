# Hermit core changes for EvoSafeHarness

EvoSafeHarness runs inside Hermit's unchanged training loop (rollout → material → one Evolver call →
check/commit). It needs three small changes to the core, all backward compatible: without the new settings,
Hermit behaves exactly as before. Together they touch 7 core files (+71/−18 lines), plus documentation and
tests. No existing field changes meaning.

## 1. Multi-metric judges: `JudgeResult.metrics` and `judge.aggregate`

**Why.** A judge returns one scalar `score`, and training and eval report its mean. A defense objective is not
such a mean:

- Utility is measured on benign tasks and attack success on injected tasks, **with separate denominators**.
- The objective is `clean utility − ASR`, and injected utility and secure completion are reported next to it.
- A run that failed counts as neither a completed task nor a blocked attack. It has to be counted on its own.

A single scalar can only mix the two meanings (utility for a clean task, `1 − attack success` for an injected
one), which makes its mean meaningless.

**What changes.**

| Item | Before | After |
|---|---|---|
| `JudgeResult` | `score, feedback, extra` | adds optional `metrics: dict` (default empty) |
| A judge's dict result | everything except `score`/`feedback` goes into `extra` | a `metrics` key goes into `metrics`; the rest still goes into `extra` |
| Config | `judge.path`, `judge.name` | adds optional `judge.aggregate` (a function in the same file/module, default `null`) |
| A failed run's `judge` | `{"score": 0.0, "feedback": ...}` | also `"metrics": {}`; `score` is still 0.0 |
| Learning material `summary.json` / `index.jsonl` | mean score, cost, ... | adds `metrics` when an aggregate is configured |
| `steps.jsonl` → `rollout` | `mean_score, scores, ...` | adds `metrics` when an aggregate is configured |
| `run_agent` tool result | `{"results": [...]}` | adds `"metrics"` when an aggregate is configured |
| `hermit eval` `summary.json` | `mean_score, solved_once, ...` | adds `metrics` (over every repeat) when an aggregate is configured |
| `hermit check` | loads the judge | also loads the aggregate, so a wrong name fails at check time |

**What does not change.** `score` is still required. `mean_score`, `solved_once`, budgets and the adapter card
use it as before.

**Contract.** `aggregate(records) -> dict` receives the run records (`id, input, status, output, judge{score,
feedback, metrics, ...}`), **including failed runs** (`status != "ok"`, empty `metrics`); the task decides how
they count. An aggregate that raises is recorded as `{"error": "..."}` and never stops a run
(`hermit.task.summarise`).

| File | Change |
|---|---|
| `hermit/task.py` | `JudgeResult.metrics`; `normalise_judge` reads `metrics`; `load_aggregate()`, `summarise()` |
| `hermit/defaults.yaml` | `judge.aggregate: null` |
| `hermit/trainer/rollout.py` | failed records carry empty `metrics` |
| `hermit/trainer/material.py` | `write(..., metrics=None)` into `summary.json` and `index.jsonl` |
| `hermit/trainer/trainer.py` | loads the aggregate; step record, material and `run_agent` carry `metrics` |
| `hermit/evaluate.py` | eval summary carries `metrics` |
| `hermit/settings_check.py` | check loads the aggregate |
| `docs/framework/task.md`, `docs/reference/config-fields.md`, `CHANGELOG.md` | documentation |
| `tests/test_judge_metrics.py` | tests |

The AgentDyn judge (`examples/agentdyn/utils/judge.py`) shows how a task uses this. `score()` returns
`metrics = {kind, utility, attack_success}`, and `summary()` computes clean utility, ASR, injected utility,
secure completions and the errors of each kind. It gives an `objective` only when every run completed.

## 2. A failed run keeps its usage and log

`hermit/trainer/rollout.py:run_one`: when the pipeline's exception carries `tokens`, `cost_usd` or `log`
attributes of a valid type, the failed record keeps them. Before, all three were always `None`. This way a
victim that made model calls but produced no final answer still leaves its trajectory and usage for diagnosis.
Only pipelines that attach these attributes are affected.

## 3. `hermit check` uses the run's sandbox setting for the template check

`hermit/settings_check.py`: the template check used the process default of `SANDBOX_ENFORCE` (`required`) rather
than the run's `sandbox.enabled/enforce`, which `train` uses. As a result, `check` failed on a configuration that
disables the sandbox, on a host without bubblewrap namespaces. Check now sets the same value as the Trainer for
the template check and restores the previous value afterwards, so one check cannot change another.

## Left to the Evolver (open for discussion)

The following stay inside the `evosafe` Evolver so the training loop is untouched. They are candidates for
framework support:

1. Records of several candidate trials within one step: the Evolver archives them in `output/`.
2. Repeated and paired evaluation: `run_agent` has no `repeats`, so the Evolver loops over it.
3. A validation gate owned by the framework: the Evolver runs validation and decides promotion itself.
4. Logs for validation runs: `run_agent` withholds them by design, so a validation failure cannot be diagnosed
   from its trajectory.
5. An enforced episode timeout without the sandbox: `agent.timeout_min` does not stop a direct function call.
