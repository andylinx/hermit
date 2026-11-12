# SHE on AgentDyn with Lightning

This integrates the four-artifact evolution mechanism from [SHE](https://github.com/RainbowQTT/SHE), pinned to
`0c656460d9d8acdf406a2271d657f7a7b60bb255`. The acting victim is frozen; only the system prompt, rule bank,
safety memory and tool policy evolve. Attacks remain the existing frozen AgentDyn cases. See the
[method page](../../../docs/methods/she.md) for the upstream comparison, selection rules and adaptation limits.

## Install and prepare

Use Python 3.12 and the [pinned, patched AgentDyn checkout](../README.md#install). Install all dependencies in
one resolver invocation so the optional benchmark cannot silently replace Hermit's constraints:

```bash
uv venv .venv-agentdyn
uv pip install --python .venv-agentdyn/bin/python -e '.[test]' --group she -e ../AgentDyn
source .venv-agentdyn/bin/activate
```

Follow the [shared preparation commands](../README.md#prepare-the-cases), including `--full-test`, to create
`../utils/data/full-test-v1`. The protocol contains 57 TRAIN, 54 validation and 186 TEST cases, from disjoint
user-task groups. TRAIN is unchanged; TEST has 18 clean and 168 injected cases. Preparation never uses model
outcomes, and injection payloads and native judges remain unchanged.

## Models and recipes

| File | Acting and runtime-judge victim | Learner | Search |
|---|---|---|---|
| `run_nemotron_codex.yaml` | Nemotron 3.5 Lightning | GPT-6 Sol Codex, high effort | 20-round cap, 12-hour budget |
| `run_nemotron_claude.yaml` | Same Lightning victim | Claude Code | Same data and gate |
| `run_nemotron_codex_daybreak.yaml` | Same Lightning victim | Codex with an explicit approved Daybreak Blue request | Same data and gate |
| `run.yaml` | Minimal custom-model example | Shared direct learner | Small configurable batches |

All Lightning recipes retain `max_iters: 25` for the acting agent. The 20-round evolution cap is separate and
follows the authors' released driver. Each round reruns all 57 TRAIN cases under the current adapter, diagnoses
failures, proposes a constrained patch and compares parent/candidate on validation. TEST is frozen evaluation
only. The native selection score and conservative treatment of unknown verdicts are documented on the method
page; clean UBR and the authors' six-condition benchmark scores are not available on this task.

Configure `vllm` outside version control, in Hermit's backend settings or a file named by `HA_BACKENDS`:

```yaml
vllm:
  base_url: https://your-model-service.example/v1
  api_key_env: VICTIM_API_KEY
  key_required: true
  apis: [chat]
```

The tested service model ID is `nvidia/nvidia/nemotron-3.5-lightning`; the repeated prefix belongs to that ID.
Use a local `models` alias if your endpoint exposes another name. Credentials never enter adapter artifacts or
learner prompts. The selective judge uses this same frozen model through the shared client, with eight bounded
calls per episode and no tools. Unknown verdicts block uncertain actions. Seed and final use identical budgets.

## Run

Commit source changes and select fresh run/tree paths before using the frozen experiment runner:

```bash
python examples/agentdyn/utils/run_experiment.py \
  --config examples/agentdyn/she/run_nemotron_codex.yaml
```

The runner freezes source, configuration, model settings and data, records installed dependency versions,
and checks Docker and the learner;
trains; then evaluates `none`, `root` and `final` on the same TEST IDs. It verifies actual learning-stage outcomes
rather than treating a successful process exit as completed search. A failed learner call preserves the parent and is recorded. A provider refusal or authentication failure
persists a stop flag and returns `stop`; recipes enable `trainer.allow_early_stop`. Even if a custom Trainer
ignores that signal, later SHE steps make no further learner calls. Refused requests are not rerouted.

The committed recipes use Hermit's existing learner sandbox and a host task pipeline that launches the learned
hooks' separate networkless Docker containers. On a machine without usable bubblewrap, a local experiment may
pass `--no-sandbox` to this runner. It freezes `sandbox.enabled=false` into the effective configuration and
records that exception as `runtime_overrides` in the snapshot manifest without editing the committed recipe. This
does not disable Docker isolation for learned artifacts. The Codex session remains read-only.

Optional Daybreak settings request approved account access, not an override of provider safety checks. Use the
extra recipe only with a CLI and account supporting that option, and record it with the experiment.

## Verification and outputs

```bash
HERMIT_TEST_DOCKER=1 python -m pytest tests/methods/she -q
python -m pytest --changed
bash docs/build.sh
```

The tests exercise the actual upstream runtime, constrained patching, native replay, fresh state, memory and
rule effects, final-response replacement, same-victim semantic judging, Docker RPC, TRAIN-only evidence,
initial-utility-floor selection, pessimistic/optimistic error bounds, and parent preservation. The fixed
specification checks run unconfined only for repository-owned test fixtures; platform sandbox checks are separate.

Per-round outputs retain `training-records.json`, diagnoses, routes, manifests, patch, candidate,
`iteration-diff.json`, `attribution.json` and `selection.json`. State retains `she-feedback.json`, including the
initial reference and installed artifact hash. Failed TRAIN episodes retain their partial public message
histories for diagnosis; reads are restricted to current TRAIN material. Episode logs include native trajectories,
tool audit,
`defense-state.json`, semantic-judge calls and metered usage. Native exceptions retain their type and a bounded stack of code locations in `failure.json`, without exception
text, source lines or local variables. State-export and cleanup failures are recorded separately in
`finalization-errors.json`; they preserve the original episode error, close remaining clients and retain known
usage. Such finalization failures remain episode errors and cannot count as successful defenses. Only shared model clients perform model calls.

The runner exports comparison reports and root/final adapters under the ignored run's `artifacts/` directory.
Keep manifests, effective config, spending, per-case records and adapter snapshots together. Do not commit
private backend settings, generated data, logs or per-run adapter snapshots.

## Measurement status

On 2026-11-12, source `62abeea6c1d6979976d516c0ddbdb413067db6d6` completed its first real 57-case TRAIN batch
with the frozen SHE seed and Lightning. This is TRAIN evidence, not TEST performance or optimization:

| Metric | Completed cases only |
|---|---|
| Clean task success | 14/18 (77.8%) |
| Injected task success | 27/33 (81.8%) |
| Attack success, lower is better | 10/33 (30.3%) |

There were six episode errors: one of 19 clean cases and five of 38 injected cases exhausted the 25-step loop
without a final assistant response. These errors are separate from completed-case denominators. The complete
selection objective is unavailable. All 57 cases, including the six errors, supplied partial public evidence.

Codex completed diagnosis of 22 failed or compromised TRAIN cases, then its provider refused the first patch
request during cybersecurity review. No candidate was generated, validated or promoted, and no TEST evaluation
ran. The controller stopped the experiment after the refusal; a partially started next TRAIN batch is retained
separately and excluded from the first-batch report. A subsequent offline-tested change makes provider refusals
stop future learner calls automatically. This run demonstrates connectivity and diagnosis, not learned gains.
The ignored run retains `artifacts/initial-train-report.json`, selection records and role logs. Dollar cost is
unknown because provider prices are unconfigured. Full optimized TEST results remain unavailable.
