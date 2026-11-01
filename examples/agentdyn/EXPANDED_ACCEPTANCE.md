# AgentDyn expanded EvoSafe acceptance

Protocol frozen 2026-11-01. Local branch development only; no push or remote PR.

## What is being accepted

The integration provides the three AgentDyn suites, structured EvoSafe-style hooks,
independent Designer/Criticizer/Analyzer Codex sessions, a fixed training cascade,
separate validation confirmation, persistent diagnosis, and final evaluation.
It ports mechanisms from `../EvoSafeHarness/domains/os-filesystem/domain_spec.md`
sections 3–5, rather than claiming the DTAP environment itself was ported.

| Capability | Implementation / limit |
|---|---|
| Prompt + executable hooks + session state | Legacy dict API and opt-in structured Defense SDK |
| Original-style contexts/results | Public schemas, trusted instruction, raw result, duration/error, mutable arguments/custom metadata |
| Recoverable refusal | PermissionError in pre/post; post refusal does not undo effects |
| Auxiliary classification | Same frozen victim, no tools, fixed prompt, bounded calls/input/time, metered |
| Independent roles | Fresh Codex process/context per Designer, Criticizer, Analyzer invocation |
| Evidence | Every case retains verdict and ordered events; per-event limits, no global JSON slicing |
| Cascade | Static check, independent review, cumulative balanced train stages 6→12→18 |
| Selection | Strict utility−ASR improvement, no clean-utility drop; fixed validation confirmation |
| Experience | Analyzer lessons and review feedback persist for subsequent proposals |
| Test discipline | Disjoint user-task groups; test runs outside search; no test evidence in role inputs |
| Robustness | Existing fixed validation cases; not original adaptive or renamed-payload probe |
| Warm starts | Prompt + identity hooks; DTAP DRIFT/CaMeL packages not transparently importable |
| Isolation | Explicit full access; no enforced filesystem or hook/judge process separation claimed |

Native judges are unchanged. Benchmark labels, hidden state and judging predicates
are not exposed to runtime hooks. Not every DTAP bundle runs unchanged: the bounded
output classifier does not implement DRIFT's planner/alignment service. Post hooks
cannot perform transactional rollback. The native runtime's internal nested-call
resolution is not separately mediated; coverage of arbitrary internal dispatch is
not claimed. Auditor truncation/timeouts return unknown and must not be called a
successful classification.

## Frozen protocol

- Model: `nvidia/nvidia/llama-3.3-nemotron-super-49b-v1.5`; API settings read from
  existing `~/project/api3.py`; no credentials copied into source.
- Config: `nvidia-expanded.yaml`; run `nemotron-agentdyn-expanded-v2`, fresh tree,
  max 3 proposals, 6 concurrent episodes per runner, one repeat.
- 54 cases: train/validation/test each 18 (6 clean +12 injected), across Shopping,
  GitHub, DailyLife. Each user-task group stays in one split. Source audits and
  fixed seed determine selection, never victim scores.
- Data SHA256: `965e6e5fb2ebd74b3fe28663d3507b2ae007c78408a2ff92f68374af254e79fe`.
- Full prepared inventory: 569 cases, 55 groups, not all model-evaluated here.
  See `AGENTDYN_DATA_AUDIT.md` for wiring checks and exclusions.
- Objective stays clean utility−ASR; injected utility and secure task completion
  are separate metrics. Errors invalidate comparison, not security wins.
- Single-repeat integration acceptance, not statistical significance evidence.

## Validation and results

Offline regression: 74 passed across bridge, backend contracts, structured SDK,
classifier, role search, expanded data, reports/budgets, Trainer and tool gates.
`hermit check --no-probe` passed for the expanded config.

Live artifacts: `runs/nemotron-agentdyn-expanded-v2/`; episodes:
`runs/expanded-episodes/`. Final measurements follow after execution; no positive
performance claim is assumed in advance.
