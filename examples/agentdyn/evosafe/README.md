# EvoSafeHarness on AgentDyn

[EvoSafeHarness](../../../docs/methods/evosafe.md) on the AgentDyn integration in [`../utils/`](../utils/). Prepare the
cases first, as described in [the AgentDyn README](../README.md#prepare-the-cases).

| File | Purpose |
|---|---|
| `run_nemotron_claude.yaml` | Nemotron Super 49B victim, Claude Code roles, all 55 eligible user groups (57 / 54 / 54) |
| `run.yaml` | A minimal sandboxed config to adapt to another victim and proposer |
| `HERMIT_CORE_CHANGES.md` | The Hermit core change the method needs |

## Run

```bash
cd examples/agentdyn/evosafe
export NVIDIA_API_KEY=...
hermit check --config run_nemotron_claude.yaml --no-probe
hermit train --config run_nemotron_claude.yaml
hermit eval  --config run_nemotron_claude.yaml --adapter root
hermit eval  --config run_nemotron_claude.yaml --adapter final
```

The roles use the authenticated `claude` CLI. Set `proposer: codex` or `proposer: llm` to use another backend. The
test split is used only by `hermit eval`.

## Results

`runs/<run>/eval/<adapter>/summary.json` has a `metrics` block with utility, ASR and the remaining defense metrics.
For a per-suite breakdown:

```bash
python ../utils/compare.py --tasks ../utils/data/all-groups-v1/tasks.jsonl --split ../utils/data/all-groups-v1/test.txt \
  --run root=runs/agentdyn-evosafe-claude/eval/root/results.jsonl \
  --run final=runs/agentdyn-evosafe-claude/eval/final/results.jsonl
```

On the 54 held-out test cases:

| Adapter | Utility | ASR |
|---|---|---|
| Initial harness | 0.44 | 0.31 |
| **EvoSafeHarness** | **0.67** | **0.06** |
