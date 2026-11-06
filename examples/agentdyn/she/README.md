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
