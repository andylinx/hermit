# AgentDyn defense bundles

[EvoSafeHarness](../methods/evosafe.md) learns a system prompt and executable defense hooks around AgentDyn's
frozen victim. The native Shopping, GitHub and DailyLife loops remain task code; all model calls use the `direct`
Base Agent. Designer, Criticizer and Analyzer sessions use the shared Claude or Codex Base Agent.

The [example README](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn) describes installation
and case preparation. `examples/agentdyn/evosafe/run_nemotron_codex.yaml` names the frozen victim backend,
learning CLI, training IDs and budgets. The Codex configuration uses disjoint training and held-out test
groups; the adapter is frozen before testing.

## Results

See the [No-defense and EvoSafeHarness comparison](https://github.com/Infini-AI-Lab/hermit/blob/main/examples/agentdyn/evosafe/README.md#results).
The Lightning comparison covers 186 fixed TEST cases and indirect injections, with runtime errors reported
separately. Both Codex and Claude recipes use the same victim and keep `max_iters: 25`; the measured
comparison uses Codex roles.

[SHE](../methods/she.md) adds a system prompt, rule bank, safety memory and tool
policy around the same fixed victim. Its [example and run records](https://github.com/Infini-AI-Lab/hermit/blob/main/examples/agentdyn/she/README.md)
describe the separate 57/54/54 training, validation and test protocol, the
conservative runtime judge and the managed Codex execution profile.
The 2026-11-06 SHE run completed diagnosis but its patch request was refused by
the provider. Its held-out comparisons evaluate the unchanged seed and do not
establish a learned improvement.

| 2026-11-06 adapter | Clean utility | Attack success | Injected utility | Errors / attempts |
|---|---:|---:|---:|---:|
| None | 11/18 | 10/34 | 18/34 | 2/54 |
| SHE seed | 10/18 | 10/35 | 18/35 | 1/54 |
| Final (unchanged seed) | 9/17 | 10/36 | 17/36 | 1/54 |

Rates use completed episodes; failed episodes are not successful defenses.
All rows cover the same 54 held-out IDs. Seed/final differences are repeat
variability, not adaptation. The example records frozen revision `a93ccca`,
the reused training evidence, provider refusal, local artifacts and uncertainty.
