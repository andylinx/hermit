## Change

Expand AgentDyn TEST from 54 to 186 existing frozen cases (18 clean, 168 injected) with `prepare_all_groups.py --full-test`. All variants remain in their original TEST-owned groups. TRAIN (57 cases), validation (54 cases), and existing payloads are unchanged. The default preparation protocol remains available; Codex uses the separate `full-test-v1` output directory.

Apply the documented patch to pinned AgentDyn revision `5353cf7` to persist newly created web pages and validate their action handlers. This fixes GitHub invitation URLs returning 404 without changing native user tasks, judges or frozen attacks.

Switch the Codex EvoSafe victim to `vllm/nvidia/nvidia/nemotron-3.5-lightning`. Keep `max_iters: 25`, GPT-6 Sol roles and the existing search/promotion settings. Update the AgentDyn README, data notes and reproduction notes; label the old 54-case scores as historical. No Hermit core, algorithm, sandbox or runtime isolation changes; generated data and experiment artifacts are excluded.

## Validation

- `python -m pytest --changed`: **898 passed, 140 skipped, 24 failed**. All 24 failures reproduce on unchanged upstream `9c45a65`, with this machine's unusable bubblewrap (`Failed RTM_NEWADDR: Operation not permitted`). Linux sandbox checks remain unverified here.
- Five new offline regressions pass (~1.6 seconds). All four native webpage tests fail on unpatched AgentDyn and pass with the patch; invitation tasks 5 and 7 pass native utility judging. Native tests require the optional patched AgentDyn dependency and otherwise skip.
- Actual preparation CLI: 57 TRAIN / 54 validation / 186 TEST; TRAIN and validation ID files are byte-identical to the original protocol. Existing rows and payloads are unchanged. The 186 TEST IDs and task fields match the previously used expanded experiment set. `Config.load` accepts the updated recipe and generated data.
- Patch application checked against the pristine pinned dependency. `git diff --check` and `bash docs/build.sh` pass.
- Offline walkthrough `hermit check`, `hermit train`, `hermit eval --adapter final` passes with local `sandbox.enabled=false`; evaluation scores 1.0 with zero errors. Committed sandbox defaults are unchanged. No new live-model training/evaluation was run for this PR.

## Review

- [x] Tests and documentation cover the affected behavior, where applicable. Tests are in the selected `evosafe` group; fixtures use frozen local cases or temporary data, no model calls, network or user credentials.
- [x] Commands, defaults, and public interfaces are consistent. Only victim model and dataset paths change in the Codex recipe; 25 iterations and search settings remain intact.
- [x] Shared logs and examples contain no credentials or private data. Native test accounts are public benchmark fixtures; generated artifacts are not committed.
- [ ] Documentation-only: links the issue where it was discussed with the core team. Not applicable: this changes code, configuration and tests.
- [x] Core and sandbox changes: none. Existing runtime boundaries are unchanged.
- [ ] Independent review (post-PR audit): pending PR creation and review of its published head.
