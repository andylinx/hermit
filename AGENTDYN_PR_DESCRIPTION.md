# Expand AgentDyn TEST and use Lightning in both EvoSafe recipes

Base: `main` · Head: `fix/agentdyn-test-lightning`

## Change

Use `vllm/nvidia/nvidia/nemotron-3.5-lightning` as the victim for both the Codex and Claude EvoSafe recipes. Both use `full-test-v1` and keep 25 search iterations. The Claude recipe uses the 54-case validation split for candidate confirmation.

Add `prepare_all_groups.py --full-test` to include all frozen variants in the 18 TEST-owned groups (18 clean, 168 injected). TRAIN has 57 cases. The preparation step preserves group ownership and frozen payloads.

Apply the documented patch to pinned AgentDyn revision `5353cf7` so newly created invitation pages remain available and their action handlers are validated. This fixes the simulated GitHub invitation 404.

## Validation

The [Lightning comparison](https://github.com/andylinx/hermit/blob/e6cc7e71461f08fe7e131530e6c30f718dd8026f/examples/agentdyn/evosafe/README.md#results) uses Codex roles on 186 TEST cases. No-defense recorded 75.0% clean utility (12/16) and 32.3% ASR (50/155). EvoSafeHarness recorded 62.5% clean utility (10/16) and 0.0% observed ASR (0/150), with 2 clean and 18 injected episode errors. Rates use completed episodes. Claude-role results are pending.

For the squashed head `e6cc7e7`, the AgentDyn tests reported **39 passed, 22 skipped**. The docs build and `git diff --check` passed. The offline `hermit check`, `hermit train`, and `hermit eval --adapter final` walkthrough passed with mean score 1.0 and zero errors using the example's best-effort sandbox on macOS. Linux sandbox enforcement remains to be verified.

Original implementation checks:

- `python -m pytest --changed`: **898 passed, 140 skipped, 24 failed**. All 24 failures reproduce on unchanged upstream `9c45a65`, with this machine's unusable bubblewrap (`Failed RTM_NEWADDR: Operation not permitted`). Linux sandbox checks remain unverified here.
- Five new offline regressions pass (~1.6 seconds). All four native webpage tests fail on unpatched AgentDyn and pass with the patch; invitation tasks 5 and 7 pass native utility judging. Native tests require the optional patched AgentDyn dependency and otherwise skip.
- Actual preparation CLI: 57 TRAIN / 54 validation / 186 TEST; TRAIN and validation ID files are byte-identical to the original protocol. Existing rows and payloads are unchanged. The 186 TEST IDs and task fields match the previously used expanded experiment set. `Config.load` accepts the updated recipe and generated data.
- Patch application was checked against the pristine pinned dependency. This update uses the recorded Lightning experiment and does not rerun it.

## Review

- [x] Tests and documentation cover the affected behavior, where applicable. Tests are in the selected `evosafe` group; fixtures use frozen local cases or temporary data, no model calls, network or user credentials.
- [x] Commands, defaults, and public interfaces are consistent. Both recipes use the documented victim and dataset paths. Each keeps its candidate selection settings.
- [x] Shared logs and examples contain no credentials or private data. Native test accounts are public benchmark fixtures; generated artifacts are not committed.
- [ ] Documentation-only: links the issue where it was discussed with the core team. Not applicable: this changes code, configuration and tests.
- [x] Core and sandbox changes: none. Existing runtime boundaries are unchanged.
- [x] Independent review (post-PR audit): reviewed `e6cc7e7`, both recipes, split handling, tests, and result accounting. No actionable findings. The source experiment artifacts and Linux sandbox were outside the verified scope.
