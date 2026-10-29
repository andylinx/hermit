# AgentDyn × EvoSafeHarness integration

This first integration evolves a defensive prompt and tool hooks using Hermit's
Trainer. It replays **existing frozen cases** in AgentDyn's native environment;
it does not create attacks. No model-backed benchmark score is claimed yet.
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
For a custom endpoint/model, the native AgentDyn provider registry must support it;
the example does not translate arbitrary Hermit model bindings into AgentDyn.

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
over completed episodes are explicitly diagnostic. Victim cost/tokens currently
remain unknown; use a wall-time limit rather than assuming a dollar budget covers
all victim spend. Proposer calls through Hermit's `llm` tool are metered.

## Verify without API calls

```bash
python -m pytest tests/test_agentdyn.py -q
```

Tests cover hook effects, score direction, data grouping and candidate selection.
With the pinned AgentDyn installed, they also exercise its native Shopping
environment, tools and judges with a scripted model and an inert vector marker.
The Trainer integration test uses deterministic task and proposer doubles.
Trusted test fixtures run without sandbox isolation; these tests do not certify
the production sandbox or model-backed defense effectiveness.
