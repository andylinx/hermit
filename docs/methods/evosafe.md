# EvoSafeHarness

EvoSafeHarness ([paper](https://andylinx.github.io/EvoSafeHarness/assets/EvoSafeHarness_paper.pdf),
[code](https://github.com/SaFo-Lab/EvoSafeHarness), [website](https://andylinx.github.io/EvoSafeHarness/))
secures a tool-using agent without touching its model. It keeps the **victim model frozen** and searches the
scaffolding around it: a **dual-surface defense bundle** made of a system-prompt surface and executable tool-call
hooks. Each candidate is written from the failure traces of the exact model it defends, scored on the exact domain
it protects (`score = utility − ASR`), and kept only when it measurably improves. The result is one runnable bundle
per *(model × domain)* cell, rather than one fixed defense for every deployment.

Its search loop has four parts:

| Part | What it does |
|---|---|
| **Designer** | Reads parent outcomes, failure traces and earlier lessons; writes one candidate bundle that changes one mechanism. |
| **Criticizer** | A fresh, independent review of the candidate: executable correctness, normal-task blockers, overfitting to benchmark strings. |
| **Cascade** | Fixed scoring gates. A candidate must keep clean utility and beat the parent's `clean utility − ASR`. |
| **Analyzer** | Explains the measured parent/candidate difference and writes lessons for the next Designer. |

In Hermit, EvoSafeHarness is the `evosafe` Evolver with the `evosafe@1.0` template. The first task integration is
[AgentDyn](https://github.com/SaFo-Lab/AgentDyn) (Shopping, GitHub and DailyLife suites), in
[`examples/agentdyn/`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn).

## When to use it

Use it when the adapter is a **defense**: the agent and its tools are fixed, the task data contains both benign
tasks and frozen attack cases (for example indirect prompt injections), and success means doing the legitimate task
while the attack's goal fails. It needs:

- a pipeline that loads the adapter's `defense.py` and calls its hooks around every tool call (a *hook bridge*);
- a judge that returns separate utility and attack-success verdicts (see [Multi-metric judges](#multi-metric-judges));
- train and validation splits that each contain clean and injected cases, grouped so that all variants of a user
  task stay in one split;
- a role backend for Designer/Criticizer/Analyzer: Claude Code (as in the original work), Codex, or the run's `llm`.

It does not generate attacks. It only replays existing frozen cases.

## Setup

```yaml
template: evosafe@1.0
data: {tasks: data/tasks.jsonl, train: data/train.txt, val: data/val.txt, test: data/test.txt,
       step_size: 30, shuffle: false}
agent:
  name: hermit.integrations.agentdyn:run        # the hook bridge for AgentDyn
  params: {model: <victim model>, ...}
judge:
  path: judge.py                                # score() and summary()
  aggregate: summary                            # clean utility, ASR, injected utility, errors, objective
evolver:
  name: evosafe
  params:
    search_mode: roles                          # Designer → Criticizer → Cascade → Analyzer
    proposer: claude                            # claude | codex | llm
    max_proposals: 3
    cascade_sizes: [30]                         # score every training case before deciding
    eval_task_ids: [...]                        # the TRAIN cases each candidate is scored on
    robustness_task_ids: [...]                  # disjoint VALIDATION cases for confirmation
    parent_error_policy: conservative_bounds
    candidate_error_policy: worst_case_bounds
    role_retries: 1
```

A full, working config is
[`examples/agentdyn/nvidia-thirty-claude.yaml`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn/nvidia-thirty-claude.yaml).

## The template: a defense bundle

`evosafe@1.0` has three learnable files and two fixed ones:

| File | Role |
|---|---|
| `ADAPTER.md` (learnable) | Prompt surface. Appended to the agent's native system prompt. |
| `defense.py` (learnable) | Executable surface. `build()` returns a `Defense` with `system_prompt_transform`, `on_pre_tool_call`, `on_post_tool_call`. One instance per episode, so per-session state is allowed. |
| `BUNDLE.md` (learnable) | Design record: evidence, parent, hypothesis, expected utility cost. Not shown to the agent. |
| `EVOLVER.md` (fixed) | The editing contract given to every role. |
| `check.py` (fixed) | Static check: files present, `defense.py` parses and defines `build()`. |

The starting bundle (`root`) is a short instruction/data boundary in `ADAPTER.md` with identity hooks.

Hooks may rewrite tool arguments, refuse a call (a recoverable tool error the agent sees), or rewrite or refuse a
tool's output. A post-hook cannot undo an effect that already happened. Hook contexts expose the trusted user
instruction and public tool schemas, **never** task IDs, injection labels, environment state or judge predicates.
Two hook APIs exist:

- the legacy dict API (`ctx` is a dict with `instruction`, `trace_id`, `tool_name`, `arguments`);
- the structured API, `hermit.integrations.evosafe_hooks` (`Defense`, `ToolCallContext`, `ToolCallResult`),
  modeled on the original's hook objects. A subclass opts in with `hook_api = "structured-v1"`. When the operator
  enables it, `ctx.classify_output(text)` is a bounded, side-effect-free classifier backed by the same frozen
  victim model.

## The step

The Trainer runs one ordinary step. EvoSafe's whole search happens inside that one Evolver call:

1. **Rollout.** The Trainer runs the current bundle on the step's training cases and writes learning material, as
   for every method. With `judge.aggregate`, the material's `summary.json` carries the defense metrics.
2. **Parent measurement.** When those rollouts exactly match the current bundle, cases and step (checked by
   content hashes), the Evolver reuses them as the parent's score. Otherwise it re-measures through `run_agent`.
   Evidence for the roles is built from the **same** rows as the score.
3. **Per trial** (up to `max_proposals`):
   - **Designer** writes the three files. Its input contains public tool contracts, parent metrics, prioritized
     paired failure cases, earlier candidates' source and traces, and accumulated lessons.
   - `check_spec` and the **Criticizer** review the candidate. A non-empty `required_changes` rejects it before
     any evaluation.
   - **Cascade.** The candidate runs on each cumulative prefix in `cascade_sizes`. Any clean-utility drop against
     the same cases of the parent rejects it. After the full set, it must beat the parent's objective.
   - **Validation confirmation.** If `robustness_task_ids` is set, parent and candidate run on those disjoint
     validation cases. The candidate must keep clean utility and must not raise ASR.
   - **Analyzer** receives the trial, paired counts and both sources, and writes a diagnosis and lessons into
     `state/lessons.json`.
   - An accepted candidate becomes the parent for the next trial.
4. The Trainer checks and commits the bundle it is handed back. A step that promoted nothing leaves the adapter
   unchanged.

Selection rule: `clean_utility − ASR` must improve strictly, by more than `min_improvement`. Clean utility may
not drop by more than `max_clean_drop` and must stay at least `min_clean_utility`.

An episode that fails to finish (for example, a victim that loops until `max_iters` without a final answer) is never
counted as a success. Two settings decide how it enters the comparison:

| Setting | `reject` (default) | Bounded |
|---|---|---|
| `parent_error_policy` | A failed parent episode rejects the step | `conservative_bounds`: the episode gets its **best** verdict (task done, attack blocked) |
| `candidate_error_policy` | A failed candidate episode rejects the candidate | `worst_case_bounds`: the episode gets its **worst** verdict (task failed, attack succeeded) |

With both bounded, a candidate is promoted only when even its worst case beats the parent's best case, so an error
can never help a candidate. Neither bound is an imputed point score. With the strict default, a single victim loop
in thirty episodes rejects an otherwise clearly better candidate.

Role calls are fresh processes. `role_retries` gives a failed `codex`/`claude` call (timeout, API error) extra
attempts. A refusal by the provider is never retried and stops the search. An Analyzer that still fails is
recorded on its trial (`analysis_error`); it neither undoes a measured result nor stops later trials.

`search_mode: single` is a simpler variant: one proposal through the run's `llm` (or a CLI), with no review or
cascade, compared with the parent on `eval_task_ids`.

## Parameters

```{literalinclude} ../../hermit/algorithms/evolvers/evosafe/evolver.yaml
:language: yaml
```

Role backends:

| `proposer` | How each role call runs |
|---|---|
| `claude` | `claude -p` with `--tools ""` (no file, shell or web access), `--no-session-persistence` and `--json-schema`. One fresh process per role call, so every role has an independent context. |
| `codex` | `codex exec --ephemeral --output-schema` in a scratch directory. One process per role call. |
| `llm` | One call of the run's `llm` tool per role. |

## Records

Under `<run>/step_NNNN/output/`:

| File | Contents |
|---|---|
| `selection.json` | Every trial's review, stage results, decision and Analyzer output |
| `parent-results.json` | Parent measurement rows |
| `trial-NNN-results.json` | Candidate rows |
| `trial-NNN-candidate/` | Each candidate's three files, archived even when it failed |
| `trial-NNN-{designer,criticizer,analyzer}-input.json` | Exact role inputs |

`state/lessons.json` carries lessons across steps. `steps.jsonl` and `learning_material/index.jsonl` carry the
aggregate metrics next to the mean score.

## Running the AgentDyn example

```bash
python examples/agentdyn/prepare_thirty.py examples/agentdyn/data/expanded-v2 examples/agentdyn/data/thirty-v1
hermit check --config examples/agentdyn/nvidia-thirty-claude.yaml --no-probe
hermit train --config examples/agentdyn/nvidia-thirty-claude.yaml
hermit eval  --config examples/agentdyn/nvidia-thirty-claude.yaml --adapter none
hermit eval  --config examples/agentdyn/nvidia-thirty-claude.yaml --adapter root
hermit eval  --config examples/agentdyn/nvidia-thirty-claude.yaml --adapter final
```

Each `eval/<adapter>/summary.json` has a `metrics` block with clean utility, ASR, injected utility, secure
completions, errors per kind, and `objective` (null unless every episode completed). The
[example README](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn) covers installation,
victim configuration and data preparation.

## Results

<!-- Filled in from the final run of this version. -->

## What it is not

Differences from the original EvoSafeHarness (DTAP domains, `domain_spec.md` §§3–5):

- **Environment.** AgentDyn application tools replace DTAP's OS, finance and telecom services. Original DTAP
  bundles (`dtap_camel_v1`, `dtap_drift_v1`) do not import unchanged and need explicit ports. The bounded output
  classifier is not DRIFT's planner/alignment service.
- **Robustness probe.** Validation confirmation replays fixed, existing cases. The original's adaptive and
  renamed-payload probes, and its over-refusal probe, are not ported. The Criticizer reviews the defense and does
  not construct attacks.
- **Cascade.** The original's Stage 0→3 (static, smoke, mid, 30-case search) with relative-utility thresholds is
  reduced to cumulative prefixes with a strict no-clean-drop gate. `cascade_sizes: [30]` scores the full 30-case
  stage directly.
- **Proposer.** The original drives all roles with Claude Code. Here roles are structured-output calls without
  tools: each one answers from the supplied evidence and does not browse the repository.
- **Isolation.** Defense hooks and the native judge share the rollout process. Without a working sandbox, role
  processes are not filesystem-isolated.

## Integrating with Hermit

### Design choices made to fit Hermit

Hermit's training loop is unchanged. EvoSafe is shaped to fit it:

| EvoSafe concept | How it maps onto Hermit |
|---|---|
| Defense bundle | An adapter from the `evosafe@1.0` template. The accepted bundle is always the current adapter, and its versions are Hermit's git tree. |
| Victim and attack replay | The task pipeline (`agent.name`). Frozen cases are task rows, and the native judge is the task judge. |
| Search iteration | One `Evolver.step()` call holding the whole Designer→Analyzer loop. Trials are archived in `output/`, and only promotions are committed. |
| Cascade scoring | The Trainer's `run_agent` tool, so every candidate episode goes through the same pipeline, judge and spending records. Test IDs are refused by the Trainer. |
| Parent score | The Trainer's own rollouts of the step, reused under hash checks instead of being run twice. |
| Held-out evaluation | `hermit eval` on the test split. Roles never see test data. |
| Experience archive | `state/lessons.json` and `state/evosafe.jsonl`, the Evolver's state directory. |
| Role sessions | External CLI processes launched per role, cancellable through the Trainer's `ctx.cancel`. |

### Changes to Hermit core

All changes are small, backward compatible and covered by tests. Without the new settings, behavior is identical
to upstream. Details and per-file diffs are in
[`examples/agentdyn/HERMIT_CORE_CHANGES.md`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn/HERMIT_CORE_CHANGES.md).

| Change | Files | Why | Proposed for upstream |
|---|---|---|---|
| **Multi-metric judges**: `JudgeResult.metrics` and an optional `judge.aggregate` recorded in material, `steps.jsonl`, `run_agent` and `eval` summaries | `task.py`, `defaults.yaml`, `trainer/{trainer,material,rollout}.py`, `evaluate.py`, `settings_check.py` | A defense objective has separate denominators and must count failed runs. A scalar mean of mixed scores is meaningless. | Yes |
| Failed episodes keep usage and log when the pipeline's exception provides them | `trainer/rollout.py` | Victim calls and trajectories of runs without a terminal answer were lost. | Yes |
| `hermit check` uses the run's sandbox setting for template checks | `settings_check.py` | `check` used the process default and failed on configs that disable the sandbox. | Yes |

Not changed in core, and handled by the Evolver instead. These are points to discuss with the Hermit team:
per-trial records inside a step, repeated and paired evaluation in `run_agent`, a framework-owned validation gate,
logs for validation runs, and an enforced episode timeout when the sandbox is disabled.

### Multi-metric judges

The AgentDyn judge returns `score` for compatibility and per-episode `metrics`
(`kind`, `utility`, `attack_success`). `summary(records)` produces the defense metrics:

```python
def score(task, output) -> JudgeResult:      # metrics = {kind, utility, attack_success}
def summary(records) -> dict:                # clean_utility_completed, asr_completed, injected_utility_completed,
                                             # secure_completions, errors_clean, errors_injected, objective
```

Failed runs are counted, never treated as blocked attacks, and `objective` stays null until every episode has
completed. See [Several metrics and a task-level aggregate](../framework/task.md#several-metrics-and-a-task-level-aggregate).
