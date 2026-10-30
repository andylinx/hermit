# AgentDyn × EvoSafeHarness integration

This first integration evolves a defensive prompt and tool hooks using Hermit's
Trainer. It replays **existing frozen cases** in AgentDyn's native environment;
it does not create attacks. Model-backed smoke results are recorded separately
from benchmark claims in [NVIDIA_SMOKE_RESULTS.md](NVIDIA_SMOKE_RESULTS.md).
See [IMPLEMENTATION.md](IMPLEMENTATION.md) for implemented behavior, verification,
limitations and remaining work.

## Install

Use a separate Python 3.12 environment. AgentDyn and upstream AgentDojo both install
as `agentdojo`; do not mix their checkouts. The reference revision is
`5353cf7615b135cace8d07c8f12dac53a16b6db3`.

From the Hermit repository root, with an AgentDyn checkout at `../AgentDyn`:

```bash
git -C ../AgentDyn checkout 5353cf7615b135cace8d07c8f12dac53a16b6db3
uv venv .venv-agentdyn
uv pip install --python .venv-agentdyn/bin/python -e '.[test]' -e ../AgentDyn
source .venv-agentdyn/bin/activate
```

Install both projects in the **same resolver invocation**, so AgentDyn's broad
dependencies cannot silently upgrade Hermit's pinned MCP packages. AgentDyn's
repository is large because it includes recorded runs; keep it outside Hermit.
The reference revision records the version tested, not automatic enforcement of
the installed checkout. Pin and record that checkout for each experiment.

## Prepare fixed cases

Prefer an explicitly selected directory of existing native trace JSON files for
one model/attack configuration, rather than pooling every published run:

```bash
python examples/agentdyn/prepare.py /path/to/selected/native/logs \
  examples/agentdyn/data --from-logs --suite shopping --seed 0
```

The importer copies only suite, user task, injection task and frozen replacements.
It drops old messages, verdicts and errors. It deduplicates identical cases, adds
a clean episode for each user task, and splits by `(suite, user_task_id)` into
approximately 60% train / 20% validation / 20% test. All variants of a user task
stay together. At least five user tasks and injected coverage in each split are
required. Existing output directories are refused.

Alternatively provide JSONL objects with these fields:

```text
suite: shopping | github | dailylife
user_task_id: existing native user-task ID
injection_task_id: existing native injection-task ID (omit for clean)
injections: mapping of existing vector IDs to frozen content (omit for clean)
```

```bash
python examples/agentdyn/prepare.py /path/to/frozen-cases.jsonl examples/agentdyn/data
```

The bridge validates task IDs and vectors against AgentDyn at execution. Preparation
does not establish that every selected user-task / injection-goal pair is meaningful;
select existing benchmark cases, review coverage, and freeze `data/manifest.json`.
The seed split is an integration protocol, not an official AgentDyn training split.

## Configure and run

`run.yaml` fixes the victim through `agent.params.model` (an AgentDyn model name).
Configure the proposer independently via Hermit's `llm`, for example an existing
configured `<backend>/<model>` reference. Export the credentials needed by both.
For a custom OpenAI-compatible endpoint/model, set `agent.params.base_url` and
`api_key_env`, or `api_script` as described below. That path bypasses the native
model-name registry while retaining AgentDyn's message/tool serialization.

```bash
hermit check --config examples/agentdyn/run.yaml --no-probe llm=YOUR_BACKEND/YOUR_PROPOSER
hermit train --config examples/agentdyn/run.yaml llm=YOUR_BACKEND/YOUR_PROPOSER
hermit eval --config examples/agentdyn/run.yaml --adapter none
hermit eval --config examples/agentdyn/run.yaml --adapter root
hermit eval --config examples/agentdyn/run.yaml --adapter final
```

Use a host with functioning bubblewrap namespaces. The example requires isolation;
do not disable it for generated defense code merely to get around a host limitation.
Update endpoint allowlists when using a different victim provider. Provider
credentials and network access are available to rollout code under the framework's
existing sandbox model; this is not a capability sandbox for arbitrary malicious Python.

Each step evaluates the parent and one proposed candidate on the same validation
cases. Acceptance requires a strictly better `clean utility − ASR` and the configured
clean-utility limits. Ties, invalid candidates and incomplete evaluations keep the
parent. Test tasks are only used by `hermit eval`. The default final adapter is the
last accepted version. Candidate artifacts, selection reports and trial history
are saved by the Trainer.

Hermit's ordinary mean score is not the defense objective. For each evaluation:

```bash
python examples/agentdyn/report.py \
  examples/agentdyn/runs/agentdyn-shopping/eval/final/results.jsonl \
  --split examples/agentdyn/data/test.txt
```

For repeated evaluation, set `eval.repeats=N` and pass `--repeats N` to the report.
Missing/duplicate episodes and errors invalidate the selection objective; metrics
over completed episodes are explicitly diagnostic. The compatible victim records
provider token usage; dollars remain unknown unless explicit per-million-token
`price: {input: ..., output: ...}` is configured. Native AgentDyn model bindings
still lack this meter. Failed episodes retain a usage sidecar when available, but
the Trainer does not add that usage to its failed-episode budget. Keep a wall-time
limit as well. Proposer calls through Hermit's `llm` tool are metered; CLI proposals
report Codex's usage via StepResult.

## NVIDIA victim and Codex evolver

`nvidia-smoke.yaml` uses NVIDIA Nemotron Super 49B v1.5 and the local authenticated
Codex CLI. It explicitly disables Hermit's sandbox for the user's authorized local
full-access experiment. The general `run.yaml` still requires isolation.

The `api_script: ~/project/api3.py` setting reads only the `base_url` and `api_key`
arguments of `OpenAI(...)`, using AST parsing. It does not execute the file, send its
example prompt, or use its original model. Literal values and simple environment
lookups are supported. The victim model is fixed separately in YAML. No credentials
are copied into run configs, prompts or checked-in files.

```bash
python examples/agentdyn/prepare_smoke.py /path/to/prepared/tasks.jsonl \
  examples/agentdyn/data/nvidia-smoke-v2
hermit check --config examples/agentdyn/nvidia-smoke.yaml --no-probe
hermit train --config examples/agentdyn/nvidia-smoke.yaml
hermit eval --config examples/agentdyn/nvidia-smoke.yaml --adapter none
hermit eval --config examples/agentdyn/nvidia-smoke.yaml --adapter root
hermit eval --config examples/agentdyn/nvidia-smoke.yaml --adapter final
```

The revised smoke selector fixes three disjoint user-task groups before execution (0 for
train, 3 for validation, 2 for test), each with a clean case and one existing frozen
injection case. This is only six episodes, suitable for debugging, not evidence of
generalization. Use a fresh `trainer.run_name` for a new experiment.
The original tasks 4 and 19 were excluded after source inspection found discrepancies
between their user requests and utility judges; see the results document. The judge
was not modified and the original exploratory results remain on disk.

`evolver.params.proposer: codex` runs `codex exec --yolo` with a JSON output schema
in a scratch directory. It uses the existing local Codex configuration/authentication
unless `codex_model` is specified. Codex returns a defensive proposal; the fixed
evolver still checks it and evaluates it before acceptance. The prompt forbids git
operations and requests no tools or file edits. Nothing in this integration pushes
or publishes a branch. On a sandboxed host, Codex auth/config access must be granted
separately; this smoke route was tested with full access.

`max_tokens`, `temperature`, `top_p`, `extra_body`, `request_timeout_s` and `max_retries`
configure compatible victim requests. Truncation and malformed tool-call arguments
fail the episode. Exhausting `max_iters` fails immediately rather than letting the
native suite silently restart against the same mutated environment.

## Verify without API calls

```bash
python -m pytest tests/test_agentdyn.py tests/test_agentdyn_live_backends.py -q
```

Tests cover hook effects, score direction, data grouping and candidate selection.
With the pinned AgentDyn installed, they also exercise its native Shopping
environment, tools and judges with a scripted model and an inert vector marker.
The Trainer integration test uses deterministic task and proposer doubles.
Trusted test fixtures run without sandbox isolation; these tests do not certify
the production sandbox or model-backed defense effectiveness.
