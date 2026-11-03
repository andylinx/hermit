# AgentDyn defense bundles

[EvoSafeHarness](../methods/evosafe.md) learns a system prompt and executable defense hooks around AgentDyn's
frozen victim. The native Shopping, GitHub and DailyLife loops remain task code; all model calls use the `direct`
Base Agent. Designer, Criticizer and Analyzer sessions use the shared Claude or Codex Base Agent.

The [example README](https://github.com/Infini-AI-Lab/hermit/tree/main/examples/agentdyn) describes installation
and case preparation. `examples/agentdyn/evosafe/run_nemotron_claude.yaml` names the frozen victim backend,
learning CLI, training/validation IDs and budgets. Evaluation is train/validation/test, grouped by user task:
57 training, 54 validation and 54 test cases, across 55 user-task groups. The accepted adapter is frozen for test.

## Results and limits

Results on the 54 held-out test cases will be added once the first evaluation of this version has run. The victim
is Nemotron Super 49B and the learner is Claude Code; this is not a GLM 5.3 Flash comparison row. Fixed-case
validation does not reproduce adaptive robustness probes, and the benchmark covers indirect injections only.
