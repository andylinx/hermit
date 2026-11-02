# EvoSafeHarness

EvoSafeHarness ([paper](https://andylinx.github.io/EvoSafeHarness/assets/EvoSafeHarness_paper.pdf),
[code](https://github.com/SaFo-Lab/EvoSafeHarness), [website](https://andylinx.github.io/EvoSafeHarness/))
secures a tool-using agent without changing its model. It keeps the victim model frozen and searches a **defense
bundle** around it: a system-prompt surface (`ADAPTER.md`) and executable tool-call hooks (`defense.py`). Each
candidate is written from the victim's own failure traces and kept only when it measurably improves
`utility − ASR`. Four parts run the search: a **Designer** proposes one mechanism, an independent **Criticizer**
reviews it, a **Cascade** scores it, and an **Analyzer** turns the results into lessons for the next proposal.

In Hermit the method is the `evosafe` Evolver with the `evosafe@1.0` template. It does not depend on any benchmark:
a domain plugs in through the [task contract](#the-task-contract). The first domain is
[AgentDyn](https://github.com/SaFo-Lab/AgentDyn), in
[`examples/agentdyn/`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn).

| Layer | Where |
|---|---|
| Method (Evolver, roles, gates, task contract, hook SDK) | `hermit/agent/evolver/methods/evosafe/` |
| Defense bundle template | `hermit/adapter/templates/evosafe/` |
| AgentDyn integration (environment bridge, victim, judge, case preparation) | `examples/agentdyn/utils/` |
| EvoSafe run configs on AgentDyn | `examples/agentdyn/evosafe/` |

## Setup

```yaml
template: evosafe@1.0
agent: {name: ../utils/bridge.py:run}                # the domain's hook bridge
judge: {path: ../utils/judge.py, aggregate: summary}
evolver:
  name: evosafe
  params:
    search_mode: roles
    proposer: claude                                 # claude | codex | llm
    gate_mode: source
    cascade_sizes: [12, 57]
    eval_task_ids: [...]                             # training cases
    robustness_task_ids: [...]                       # validation cases
```

A full config is [`examples/agentdyn/evosafe/run_nemotron_claude.yaml`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn/evosafe/run_nemotron_claude.yaml).
The method does not generate attacks; it replays existing frozen cases.

## The task contract

A domain provides four things:

1. **Case fields** on every task row: `kind` (`clean` or `injected`), and optionally `group` (the cases of one user
   task, kept in one split) and `domain` (a stratum for balanced evaluation).
2. **A judge** whose `JudgeResult.metrics` holds `{kind, utility, attack_success}`, with
   `judge.aggregate: summary` from the method's `contract.py`.
3. **A hook bridge** as the task pipeline. It builds the bundle's `Defense` once per episode and calls its hooks
   around every tool call, as the template's `.hermit/EVOLVER.md` specifies. Hooks see the trusted instruction and
   public tool schemas, never task IDs, labels or judge state.
4. **A domain specification** in `task_info` (`README.md`, `tools.json`), which every role receives.

To add a domain, follow `examples/agentdyn/utils/` and copy the AgentDyn run config.

## The step

1. Hermit rolls the current bundle out on the step's training cases. These rollouts are the parent's score.
2. For up to `max_proposals` trials, the Designer writes one candidate. A fresh Criticizer reviews it, and a
   rejected candidate is revised up to `review_revisions` times before any evaluation.
3. An approved candidate is scored on the training cases. With `gate_mode: source`, the source method's gates
   apply:
   - an intermediate stage needs utility ≥ 0.7× and ASR ≤ 1.3× the parent's;
   - promotion needs a gain in `utility − ASR` above `min_improvement`;
   - validation needs an objective within `validation_tolerance` of the parent's.
4. The Analyzer records lessons for the next trial. A promoted candidate becomes the parent.

## Parameters

```{literalinclude} ../../hermit/agent/evolver/methods/evosafe/evolver.yaml
:language: yaml
```

## Integrating with Hermit

The training loop is unchanged; the whole search runs inside one `Evolver.step()`. The method needs one core
addition, **multi-metric judges**: `JudgeResult.metrics` and an optional `judge.aggregate`. A defense objective has
separate denominators that a mean of scalar scores cannot express. See
[Several metrics and a task-level aggregate](../framework/task.md#several-metrics-and-a-task-level-aggregate) and
[`HERMIT_CORE_CHANGES.md`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn/evosafe/HERMIT_CORE_CHANGES.md).

## What it is not

- The original's adaptive and renamed-payload robustness probes are not ported. Validation replays fixed cases.
- DTAP seed bundles (DRIFT, CaMeL) need an explicit port to this hook contract.
- Hook code runs next to the domain's judge in the rollout process, so it is not isolated from it.

## Example

[`examples/agentdyn/evosafe/`](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn/evosafe) runs the
setup on AgentDyn: Llama-3.3-Nemotron-Super-49B as the victim, Claude Code roles, and all 55 eligible user groups.
Results on the 54 held-out test cases:

| Adapter | Utility | ASR |
|---|---|---|
| Initial harness | 0.44 | 0.31 |
| **EvoSafeHarness** | **0.67** | **0.06** |
