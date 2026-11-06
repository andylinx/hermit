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
