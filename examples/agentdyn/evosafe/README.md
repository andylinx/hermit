# EvoSafeHarness on AgentDyn

[EvoSafeHarness](../../../docs/methods/evosafe.md) on the AgentDyn integration in [`../utils/`](../utils/). Prepare the
cases first, as described in [the AgentDyn README](../README.md#prepare-the-cases).

| File | Purpose |
|---|---|
| `run_nemotron_claude.yaml` | Nemotron Super 49B victim, Claude Code roles, all 55 eligible user groups (57 / 54 / 54) |
| `run.yaml` | A minimal sandboxed config to adapt to another victim and proposer |
| `FRAMEWORK_SUPPORT.md` | How the method fits Hermit without core changes, and candidates for framework support |

## Run

The Nemotron config uses Hermit's built-in `vllm` backend, which defaults to a local OpenAI-compatible server.
To use another service, override that backend in your own `~/.config/hermit/backends.yaml`, or in a file named
by `HA_BACKENDS`. Keep the actual endpoint and credential settings outside version control. For example:

```yaml
# ~/.config/hermit/backends.yaml (local settings)
vllm:
  base_url: https://your-model-service.example/v1
  api_key_env: VICTIM_API_KEY
  key_required: true
  apis: [chat]
```

If the service uses a different model ID, add a `models` alias from
`nvidia/llama-3.3-nemotron-super-49b-v1.5` to that ID in the same local backend file. You can also use another
registered backend with `agent.model=<backend>/<model-id>` on the command line.

```bash
cd examples/agentdyn/evosafe
export VICTIM_API_KEY=...  # when required by your local backend
# Optional per-checkout settings: export HA_BACKENDS="$PWD/backends.local.yaml"
hermit check --config run_nemotron_claude.yaml --no-probe
hermit train --config run_nemotron_claude.yaml
hermit eval  --config run_nemotron_claude.yaml --adapter root
hermit eval  --config run_nemotron_claude.yaml --adapter final
```

The roles use the shared `claude` Base Agent with the authenticated CLI. To use Codex, replace `base: claude`
and the `claude:` section with `base: codex` and `codex: {web_search: false, timeout_s: 600}`. Set `evolver.model`
for a provider binding or `{name: ..., login: chatgpt}` for Codex's shared login-plan behavior. For direct model
proposals, use `base: direct`, `evolver.model: <backend>/<model>` and `params.proposer: llm`.
The test split is used only by `hermit eval`.

## Results

`hermit eval`'s `mean_score` is not a defense metric. Compute utility, ASR, the objective and the error counts from
an evaluation's records:

```bash
python ../utils/report.py runs/agentdyn-evosafe-claude/eval/final/results.jsonl --split ../utils/data/all-groups-v1/test.txt
```

For a per-suite breakdown:

```bash
python ../utils/compare.py --tasks ../utils/data/all-groups-v1/tasks.jsonl --split ../utils/data/all-groups-v1/test.txt \
  --run root=runs/agentdyn-evosafe-claude/eval/root/results.jsonl \
  --run final=runs/agentdyn-evosafe-claude/eval/final/results.jsonl
```

Results on the 54 held-out test cases will be added once the first evaluation of this version has run.
