# Expand AgentDyn TEST coverage and switch both Codex and Claude victims to Nemotron 3.5 Lightning

Base: `main` · Head: `fix/agentdyn-test-lightning`

## Change

Expand AgentDyn TEST from 54 to 186 existing frozen cases (18 clean, 168 injected) with `prepare_all_groups.py --full-test`. All variants remain in their original TEST-owned groups. TRAIN (57 cases), validation (54 cases), and existing payloads are unchanged. The default preparation protocol remains available; both Codex and Claude use the separate `full-test-v1` output directory.

Apply the documented patch to pinned AgentDyn revision `5353cf7` to persist newly created web pages and validate their action handlers. This fixes GitHub invitation URLs returning 404 without changing native user tasks, judges or frozen attacks.

Set both Codex and Claude EvoSafe victims to `vllm/nvidia/nvidia/nemotron-3.5-lightning`. Keep `max_iters: 25`, each recipe's existing learner roles and search/promotion settings. Update the AgentDyn README, data notes, method guide and reproduction notes with the Lightning configuration and measured 186-case Codex results. No Hermit core, algorithm, sandbox or runtime isolation changes; generated data and experiment artifacts are excluded.

Measured Lightning results (Codex roles, one repeat, 25-iteration limit):

| Adapter | Clean utility | Clean errors | ASR | Injected errors |
|---|---:|---:|---:|---:|
| No-defense (`none`) | 75.0% (12/16) | 2 | 32.3% (50/155) | 13 |
| Initial (`root`) | 55.6% (10/18) | 0 | 28.7% (45/157) | 11 |
| EvoSafeHarness (`final`) | 62.5% (10/16) | 2 | 0.0% (0/150) | 18 |

Rates use completed episodes; errors are reported separately, never as secure successes. The final run has 20 errors and no complete-run defense objective. This recorded run used local `sandbox.enabled=false` with learned hooks in networkless Docker; committed sandbox defaults remain enabled. Claude-role results have not been measured.

## Validation

Results from implementation checks:

- Initial update (`6a477f3`), `python -m pytest --changed`: **898 passed, 140 skipped, 24 failed**. All 24 failures reproduce on unchanged upstream `9c45a65`, with this machine's unusable bubblewrap (`Failed RTM_NEWADDR: Operation not permitted`). Linux sandbox checks remain unverified here.
- Latest follow-up: 33 affected backend, webpage and TEST-preparation tests pass; both recipe configurations load, with only model IDs and dataset paths differing from upstream. The README table was recomputed from all 558 raw evaluation records and matches the saved comparison. The run manifest and private backend mapping confirm Lightning; the native dependency matches the webpage patch exactly.
- Five new offline regressions pass (~1.6 seconds). All four native webpage tests fail on unpatched AgentDyn and pass with the patch; invitation tasks 5 and 7 pass native utility judging. Native tests require the optional patched AgentDyn dependency and otherwise skip.
- Actual preparation CLI: 57 TRAIN / 54 validation / 186 TEST; TRAIN and validation ID files are byte-identical to the original protocol. Existing rows and payloads are unchanged. The 186 TEST IDs and task fields match the previously used expanded experiment set. `Config.load` accepts the updated recipe and generated data.
- Patch application checked against the pristine pinned dependency. `git diff --check` and `bash docs/build.sh` pass.
- Offline walkthrough `hermit check`, `hermit train`, `hermit eval --adapter final` passes with local `sandbox.enabled=false`; evaluation scores 1.0 with zero errors. Committed sandbox defaults are unchanged. The published metrics come from the completed 2026-11-11 run `agentdyn-evosafe-codex` at framework `9c45a65`; this update issued no new live-model calls.

## Review

- [x] Tests and documentation cover the affected behavior, where applicable. Tests are in the selected `evosafe` group; fixtures use frozen local cases or temporary data, no model calls, network or user credentials.
- [x] Commands, defaults, and public interfaces are consistent. Only victim model and dataset paths change in both recipes; 25 iterations and search settings remain intact.
- [x] Shared logs and examples contain no credentials or private data. Native test accounts are public benchmark fixtures; generated artifacts are not committed.
- [ ] Documentation-only: links the issue where it was discussed with the core team. Not applicable: this changes code, configuration and tests.
- [x] Core and sandbox changes: none. Existing runtime boundaries are unchanged.
- [ ] Independent review (post-PR audit): pending PR creation and review of its published head.
