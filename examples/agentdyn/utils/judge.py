"""AgentDyn's judge for EvoSafe: native verdicts as per-episode metrics (bridge.score), and the method's
defense metrics as the task-level aggregate (judge.aggregate: summary)."""
from bridge import score
from hermit.agent.evolver.methods.evosafe.contract import summary

__all__ = ["score", "summary"]
