# AgentDyn × SHE

This integrates [RainbowQTT/SHE](https://github.com/RainbowQTT/SHE) revision
`0c656460d9d8acdf406a2271d657f7a7b60bb255` into Hermit, reusing the existing
AgentDyn fixed-case replay and native utility/injection judges. It does not
generate attacks or reproduce SHE's Agent-SafetyBench experimental results.

## Install and run

Use the same pinned AgentDyn checkout as [AgentDyn README](../README.md), in a separate
Python 3.12 environment. Install all dependencies in one resolver invocation:

```bash
uv venv .venv-agentdyn
uv pip install --python .venv-agentdyn/bin/python -e '.[test]' \
  --group she -e /path/to/AgentDyn
source .venv-agentdyn/bin/activate
```

`--group she` installs the pinned upstream runtime, diagnosis, manifest and patch
implementation. Seed artifacts are packaged with `she@1.0`, together with their
upstream license and revision. There is no dependency on the temporary checkout
used during development.

Prepare grouped, disjoint train/validation/test data with the existing AgentDyn
preparation scripts. `run.yaml` uses `../utils/data/{tasks.jsonl,train.txt,val.txt,test.txt}`
and a separate run name. Configure the fixed victim and proposer credentials as
described in the AgentDyn README, then run:

```bash
hermit check --config examples/agentdyn/she/run.yaml --no-probe llm=YOUR_BACKEND/YOUR_PROPOSER
hermit train --config examples/agentdyn/she/run.yaml llm=YOUR_BACKEND/YOUR_PROPOSER
hermit eval --config examples/agentdyn/she/run.yaml --adapter none
hermit eval --config examples/agentdyn/she/run.yaml --adapter root
hermit eval --config examples/agentdyn/she/run.yaml --adapter final
```

The existing `report.py` and `compare.py` work unchanged. For the previous
NVIDIA/all-groups setup, `run_nemotron_claude.yaml` retains its frozen
victim and data paths, selects Claude Code for the debugger and evolver, and uses
a separate SHE run/tree directory. Like the previous local experiment config it
disables isolation; the general `run.yaml` requires isolation. It does not reuse
EvoSafe defense artifacts or the optional EvoSafe output classifier.

`evolver.base` supports `direct`, `codex`, and `claude`, using the existing
metered Hermit/CLI interfaces. Both SHE stages use the selected provider. The CLI
response envelope is decoded before SHE validates the inner JSON. A failed call
or provider safety refusal retains the parent and is recorded without retries.
`debugger: deterministic` uses upstream heuristic routing without a debugger LLM
call; the default `debugger: llm` refines the owner, explanation and normalized
risk dimensions before proposing a patch.

## Implemented method

1. Load a fresh upstream SHE runtime per episode. Compose the system prompt and
   active safety memories, preprocess the user query, check tools before execution,
   filter their results, deliver warnings, and check the final answer before the
   native judge. Preserve the original user goal for tool safety decisions.
2. Diagnose only current training material. Map AgentDyn injected episodes to
   SHE's `indirect_injection` condition and clean episodes to `clean`; preserve
   native verdicts and observable tool events. Runtime state is read only from
   copied training trajectories, never from validation/test logs.
3. Use upstream failure routing, normalized risk axes and evidence-backed patch
   manifests. The LLM debugger may refine the primary owner. The evolver can edit
   only diagnosed artifact owners and, by default, only one artifact per step.
4. Apply upstream constrained patch operations and full bundle validation, then
   Hermit's fixed-file/size/specification checks. Python runtime code is fixed.
5. Evaluate parent and candidate on the entire validation split. Require complete,
   unique results with both clean and injected coverage. ASR must not increase;
   clean utility and injected utility must not decrease; at least one metric must
   strictly improve by more than `min_improvement`. Also enforce
   `min_clean_utility`. Ties, errors and invalid patches retain the parent.
6. Keep training-only feedback, cross-round diffs, persistent failures and patch
   history. Attribute accepted manifests only when the installed artifact hash
   matches the previous promotion and a case was observed in both rounds.
   Non-overlapping training batches do not establish a fix or regression.

The four learnable files are `artifacts/system_prompt.md`, `rule_bank.jsonl`,
`safety_memory.jsonl`, and `tool_policy.json`. `max_updated_artifacts` can be set
from 1 to 4. The final adapter is the last accepted version managed by Trainer.

Episode logs include `defense-state.json` (rules, memories, warnings, judge calls,
tool decisions and execution positions), native trajectories, and a defense hash
covering all four artifacts. Step outputs include `training-records.json`,
`diagnosis/`, `routes.json`, `manifests.json`, `applied-manifests.json`, `patch.json`, `candidate/`,
`iteration-diff.json`, `attribution.json`, and `selection.json` when those stages
run. State contains `she.jsonl` and `she-feedback.json`.

## Adaptation limits

- The runtime uses SHE's deterministic conservative fallback for selective judge
  escalation: uncertain calls are blocked. It does not silently import an
  unrelated Agent-SafetyBench LLM client or spend extra judge tokens. This may
  reduce utility; it is distinct from the model-backed evolution debugger.
- AgentDyn supplies tool registry membership, but has no upstream SHE signed
  registry, so signature verification is not claimed. Tool names and argument
  schemas remain native AgentDyn names; benchmark-specific upstream sink rules
  only apply where names and arguments match. Evolution can add native rules.
- There are no synthetic context/memory/tool-tampering conditions or harmful-clean
  unsafe-behavior labels. We report native ASR and clean/injected utility, not
  SHE's UBR. Selection is an explicit strict Pareto adaptation; the upstream
  Bayesian belief reports and alternate initial-UA-floor mode are not enabled.
- One patch is proposed per Trainer step; increase epochs for repeated evolution.
  Training evidence clips individual event content to the configured budget.
  It is observable trajectory evidence, not a claim to capture private reasoning.
- Post-tool filtering cannot undo an executed side effect. Final-answer replacement
  likewise changes the response, not environment state. Invalid/incomplete
  episodes never count as successful defenses.

## Offline verification

```bash
HERMIT_TEST_DOCKER=1 python -m pytest tests/methods/she tests/methods/evosafe -q
```

The SHE tests cover native AgentDyn replay with a scripted model, pre-execution
blocking, output processing, final-answer replacement, artifact hashes, fresh
state, LLM diagnosis with deterministic responses, constrained patch validation,
training-data boundaries, parent preservation and selection regressions. They
do not establish model-backed defense effectiveness.

Verified on 2026-11-04 with the pinned AgentDyn and the git-installed SHE package:
74 AgentDyn tests passed; the optional-evolver checks added 3 passes and 7 skips
(uninstalled unrelated method dependencies). All 6 specification tests passed
with sandboxing disabled only for repository-owned test fixtures. The default
specification test invocation hit this host's existing bubblewrap loopback
permission failure; sandbox enforcement has not been validated here. The NVIDIA
SHE example also passed `hermit check --no-probe`. No paid model experiment was run.


## Current main and Codex (2026-11-06)

The implementation follows the current template metadata layout (`.hermit/`),
method directories and shared Base Agents. Runtime hooks execute in the same
networkless, read-only Docker boundary as EvoSafe. Only the four artifacts,
fixed bridge and pinned SHE library are mounted; native tools/judges and provider
credentials stay outside. The query, final-response and state RPCs are available
for SHE, with the ordinary EvoSafe behavior preserved.

`run_nemotron_codex.yaml` runs the frozen 57/54/54 protocol with a read-only Codex
learner. It uses `approval_policy="on-request"`, not `--yolo`. In the current
managed installation, a harmless `--yolo` probe returned an answer but enterprise
requirements rejected both `Never` and `DangerFullAccess` and enforced the
managed restricted profile. There was no successful full-access Codex execution.

Configure `vllm` to point at the established NVIDIA endpoint using Hermit's
private backend file and an environment variable for its key, then run:

```bash
python examples/agentdyn/utils/run_experiment.py \
  --config examples/agentdyn/she/run_nemotron_codex.yaml
```

The runner freezes committed source, configuration and inputs, checks Docker and
the learner, then runs training and all three held-out evaluations. Each invocation
needs fresh run/tree paths. Raw records stay in ignored local run directories.

### Validation on the rebased branch

The branch was rebased onto `48cf908` (`origin/main` on 2026-11-06). The focused
SHE and EvoSafe suite passed 228 tests, including real networkless Docker hook
execution. After adding batching, shared Base Agent and upstream JSON-fence
coverage, the SHE suite passed all 27 tests with `HERMIT_TEST_DOCKER=1`.
The documentation build passed with warnings treated as errors, as did the
offline check/train/eval walkthrough.

The affected-suite run reported 795 passed, 60 skipped and 26 failed. All 26
failures were reproduced individually on a clean archive of `48cf908`; this
host denies the bubblewrap network/UID mapping needed by those sandbox and
deployment tests. These checks do not establish working bubblewrap isolation
on this host.

The first model-backed run, `nemotron-agentdyn-she-codex-20261106` at `fb26c36`,
completed all 57 training attempts with 3 episode errors. Its third debugger
response contained valid JSON inside the upstream `SAFETY_AXES_JSON` fence;
the integration's plain-JSON decoder rejected it. Training preserved the seed,
and the experiment audit stopped before validation/test. Its local records
remain unchanged. Revision `5e55c77` accepts a single complete JSON fence and
rejects mixed prose or multiple blocks; it also covers the actual failed
response. The second run uses fresh run and tree paths with suffix `-r2`.

The second run completed 57 training attempts with 3 errors: one missing terminal
response and two episode deadlines. Its debugger returned a diagnosis object
followed by a separate upstream axes block, exposing conflicting formatting
instructions. Revision `a93ccca` retains the upstream diagnosis requirements but
replaces that formatting section with a batched typed schema passed directly to
the CLI Base Agent. All 29 SHE tests pass with real Docker enabled.

### Learning outcome and evaluation scope

The `-r3` continuation freezes `a93ccca` and reuses **all** `-r2` training records,
including errors and original trajectories. The driver verifies seed, task-input
and evidence hashes; it does not rerun or filter training attempts. Its source
and provenance are saved in the run's local `artifacts/` directory. Cached
training spending is recorded separately from new learning/evaluation spending.

Eight typed diagnosis batches completed, covering 30 failed or compromised
cases. The subsequent `she-evolve` request was refused by the provider's
cybersecurity content review (`SAFETY_REVIEW_REFUSAL`). The request was not retried
or rerouted. No candidate was generated, no validation comparison occurred, and
the four final artifacts have exactly the seed hash:
`adb9eab6d61cf522ff3099206f4c7c68241b79763aeabe4e26c400afb9c4ab36`.

The held-out none/root/final evaluations are therefore diagnostic evaluations
after **incomplete learning**, not evidence of an evolved SHE improvement.
Root and final are the same adapter; any score difference between them is
repeat variability. This is distinct from the `--yolo` permission restriction:
ordinary managed Codex calls succeeded, while the patch request was refused
based on its content.

### Held-out results (2026-11-06)

All three evaluations attempted the same 54 held-out cases: 18 clean and 36
injected, from 18 disjoint user-task groups. Each case has one attempt per
evaluation. Rates below use completed episodes only; errors remain separate
and are never credited as successful defenses.

| Adapter | Clean utility | Attack success rate | Injected utility | Errors / attempts |
|---|---:|---:|---:|---:|
| None | 11/18 (61.1%) | 10/34 (29.4%) | 18/34 (52.9%) | 2/54 |
| SHE seed (`root`) | 10/18 (55.6%) | 10/35 (28.6%) | 18/35 (51.4%) | 1/54 |
| Unchanged seed (`final`) | 9/17 (52.9%) | 10/36 (27.8%) | 17/36 (47.2%) | 1/54 |

The baseline errors were two injected GitHub episode deadlines. The seed's
error was one injected GitHub episode without a terminal answer; the final
repeat's error was one clean GitHub episode without a terminal answer. All
three runs have full ID coverage but incomplete valid verdicts, so their
selection objectives are null. The 17 clean cases completed by both seed
repeats have identical utility outcomes; the eighteenth is an error in the
final repeat. The small ASR differences are not a learned improvement: every
evaluation recorded 10 successful attacks, with different valid denominators.

The frozen continuation took 4,851 seconds (80.9 minutes), including diagnosis
and the three held-out evaluations. The test runs recorded 3,094,841,
3,422,116 and 3,528,230 tokens respectively; new learner calls recorded 176,179
tokens. Reused training records came from 2,680,677 rollout tokens in `-r2`;
earlier failed attempts are retained separately. Provider prices were not
configured, so dollar cost is unknown, not zero. Single-pass results and the
descriptive Wilson intervals in `comparison.json` do not establish statistical
significance, especially because injection variants share user tasks.

Local records under `runs/nemotron-agentdyn-she-codex-20261106-r3/` include:

- `artifacts/manifest.json`: source revision, frozen inputs, original evidence
  hashes, replay provenance, training failure and evaluation status.
- `artifacts/comparison.json`, `*-report.json` and `*-results.jsonl`: aggregate
  and per-case results, denominators, errors, paired clean outcomes and intervals.
- `artifacts/root/` and `artifacts/final/`: identical learned artifacts.
- `workspace/output/`: all eight diagnoses, routes, manifests and the provider
  refusal trajectory. There is no candidate patch or validation score.
- `artifacts/replay-driver.py` and `review-artifacts.tar.gz`: the exact local
  continuation driver and the structured review bundle. All recorded artifact
  hashes were verified after completion.

These files are ignored local outputs, not published benchmark artifacts.
The overall run status is `complete_with_errors` with `training_complete=false`.

### Explicit Daybreak retry

`run_nemotron_codex_daybreak.yaml` adds the documented per-turn CLI option
`--cyber-access-program daybreak_blue` to the same `gpt-6-sol` learner, while
retaining managed permissions. This option requests approved access; it does
not grant account access. See the [official CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
An explicit no-tool probe returned successfully, and the shared role preflight
also passed. Exec JSONL does not expose a separate selected-program field.

The retry `nemotron-agentdyn-she-codex-daybreak-20261106-r1` froze `af5ef91` and
reused all 57 original training records, including errors. All eight diagnosis
batches completed. **Patch generation succeeded this time**: the candidate
appends one `after_tool` warning detector to `artifacts/tool_policy.json` for
untrusted content that presents an unrelated action as a task prerequisite.
It passed the static specification check and remained within the one-file budget.

The parent then attempted all 54 validation cases. There were 50 valid native
verdicts, three retained failure records and one case without a retained native
verdict. The shared tool log truncates large results, so the audit was
reconstructed from native result/task hashes and failure files; the exact error
text for the missing verdict is unavailable. The diagnostic parent metrics are
clean utility 6/18, ASR 8/32 and injected utility 14/32. These are **validation**
metrics, not the held-out test row above. The complete-validation gate rejected
the comparison (`evaluation has missing/failed episodes`); candidate validation
never started, and the candidate was not accepted. This does not establish
whether the generated patch helps or hurts.

The final acting artifacts remained identical to the seed. After checking the
acting configuration, runtime code, data and artifact hashes (excluding the
non-runtime `.hermit/CARD.md` bookkeeping), the automatically started duplicate
held-out replay was stopped. The completed `-r3` test results above are reused
with explicit provenance; partial new test records are excluded. The driver's
manifest preserves that interruption rather than claiming a fresh completed
test run. `artifacts/outcome.json` records the completed learning attempt and
its incomplete validation separately.

Local retry artifacts include `candidate/`, `patch.json`, `selection.json`,
`parent-validation-reconstructed.jsonl`, `parent-validation-report.json`,
`daybreak-preflight.json`, `reuse-decision.json` and `reused-test/`. The review
bundle includes their checksums. The metered search (diagnosis, proposal and
parent validation) recorded 3,625,148 tokens; it excludes cached training and
may omit interrupted duplicate-test usage. Dollar cost remains unknown.
