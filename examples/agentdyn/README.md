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

## Expanded EvoSafe role search

`nvidia-expanded.yaml` uses independent Codex Designer, Criticizer and Analyzer
sessions, with a fixed Python evaluation cascade between review and analysis.
The role prompts adapt `../EvoSafeHarness/domains/os-filesystem/domain_spec.md`
sections 3–5: one evidence-based mechanism per candidate, independent utility and
anti-overfit review, staged measurements, and persistent lessons. The Criticizer
reviews defensive code; this integration does not generate attacks. The fixed-case
validation confirmation is not the original adaptive/renamed-attack robustness probe.

The cascade uses training cases, retaining their observable tool events for the
Analyzer. Every case keeps its outcome and event sequence; per-event clipping replaces
the old global string truncation. Prospective improvements are checked on disjoint
validation groups. Final test results never go into role inputs or selection.
Strict clean-utility protection and the original `clean utility - ASR` objective
remain in place. Injected utility and secure task completion are reported separately.

The optional structured SDK is `hermit.integrations.evosafe_hooks`: original-style
contexts/results, public tool schemas, per-episode state, argument/result mutation,
and recoverable `PermissionError` refusals. It is an explicit portable contract,
not a fake DTAP import package. An optional operator-configured classifier uses only
the same frozen victim, has no tools, and reports bounded classification usage.
A post-hook cannot undo an already executed side effect.

Prepare a fresh expanded dataset from one existing source collection:

```bash
python examples/agentdyn/prepare_expanded.py \
  /path/to/AgentDyn/runs/google_gemini-2.5-flash \
  examples/agentdyn/data/expanded-v2
hermit check --config examples/agentdyn/nvidia-expanded.yaml --no-probe
hermit train --config examples/agentdyn/nvidia-expanded.yaml
hermit eval --config examples/agentdyn/nvidia-expanded.yaml --adapter none
hermit eval --config examples/agentdyn/nvidia-expanded.yaml --adapter root
hermit eval --config examples/agentdyn/nvidia-expanded.yaml --adapter final
```

The acceptance subset contains 54 episodes across Shopping, GitHub and DailyLife:
18 per split, each with six clean episodes and twelve existing injected episodes.
Splits are disjoint by `(suite, user_task_id)`. Selection uses a fixed seed and
source-level checks, not model performance. See `AGENTDYN_DATA_AUDIT.md` for exclusions,
the full eligible inventory, and the limits of the native initialization checks.
The config freezes exact training and validation IDs, so update those lists when
creating a different protocol. Use a fresh run name and tree directory after changing
the template's fixed contract; don't reuse historical experiment trees.

Compare completed runs with counts, errors and per-suite/per-goal breakdowns:

```bash
python examples/agentdyn/compare.py \
  --tasks examples/agentdyn/data/expanded-v2/tasks.jsonl \
  --split examples/agentdyn/data/expanded-v2/test.txt \
  --run none=examples/agentdyn/runs/nemotron-agentdyn-expanded-v2/eval/none/results.jsonl \
  --run final=examples/agentdyn/runs/nemotron-agentdyn-expanded-v2/eval/final/results.jsonl
```

This is broader integration acceptance, not the full official benchmark or a
statistically conclusive improvement claim. Full access is explicitly configured
for this local experiment; prompt instructions and event audits do not constitute
filesystem isolation of the Codex roles.

The follow-up `nvidia-expanded-diverse.yaml` keeps the same frozen victim/cases and
acceptance metrics, but schedules distinct mechanism families after the first search
repeatedly proposed brittle action-list guards. `mechanism_schedule: []` retains
unrestricted Designer mechanism choice. Independent review approves a candidate for
empirical evaluation, not as a proof of complete security coverage. See
`EXPANDED_ACCEPTANCE.md` for all rejected trials and the separate benign diagnostic.
For the recorded follow-up, the preceding run's `workspace/state/lessons.json` was
copied into the fresh run's `workspace/state/lessons.json` before `hermit train`;
only training-side lessons were carried over, never test results.

### Paired failure debugging and 30-case scoring

The original Harness's scored stage has 30 cases. The follow-up protocol uses
30 cases per split (10 clean, 20 injected from 10 user-task groups), keeps all old
split ownership, and scores the entire training batch before the utility gate:

```bash
python examples/agentdyn/prepare_thirty.py \
  examples/agentdyn/data/expanded-v2 examples/agentdyn/data/thirty-v1
python examples/agentdyn/debug_failures.py \
  examples/agentdyn/runs/nemotron-agentdyn-expanded-diverse-v2 \
  examples/agentdyn/runs/paired-debug-v1 --analyze
hermit train --config examples/agentdyn/nvidia-thirty.yaml
```

`debug_failures.py` works on a recorded search with an unchanged parent. It reads
training logs only, preserves all verdicts, builds paired detailed failure dossiers,
and optionally runs fresh Codex Analyzers. `--resume` reuses completed diagnostics.
The live search now forwards failed candidate source and dossiers directly to the
next Designer and refreshes parent evidence from the same measurements as its score.
The dossier subset is for diagnosis, never a different scoring denominator.

For the recorded thirty-case run, corrected analyses seed `workspace/state/lessons.json`;
the last paired diagnostic seeds `workspace/state/previous_candidate_evidence.json`.
Only IDs in the current training selection are accepted by the seed check. Seed
provenance is recorded separately in the run directory. Starting without these
optional seed files is valid but does not reproduce the exact recorded search.
