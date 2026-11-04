"""SHE's artifact runtime adapted to AgentDyn's per-episode defense contract."""
from pathlib import Path

SHE_REVISION = "0c656460d9d8acdf406a2271d657f7a7b60bb255"
ARTIFACTS = ("system_prompt.md", "rule_bank.jsonl", "safety_memory.jsonl", "tool_policy.json")


def require_she():
    try:
        import she.runtime.artifacts  # noqa: F401
    except ImportError:
        from hermit.agent.evolver.dependencies import missing_dependency
        raise missing_dependency("she", "the SHE runtime and evolution library", "she") from None


def validate_bundle(root):
    require_she()
    from she.evolution.artifact_patcher import validate_artifact_bundle
    root = Path(root)
    files = {f"artifacts/{name}": (root / "artifacts" / name).read_text() for name in ARTIFACTS}
    validate_artifact_bundle(files)


class SHEDefense:
    hook_api = "structured-v1"
    artifact_paths = tuple(f"artifacts/{name}" for name in ARTIFACTS)

    def __init__(self, root):
        require_she()
        from she.runtime.artifacts import load_runtime_from_artifacts
        from she.runtime.runtime_adapter import SHERuntimeAdapter

        class AgentDynAdapter(SHERuntimeAdapter):
            def _check_registry_integrity(self, call):
                # AgentDyn has no SHE/Agent-SafetyBench signed tool registry.
                # Membership is still checked through _is_registered_tool.
                return None

        validate_bundle(root)
        self.adapter = AgentDynAdapter(load_runtime_from_artifacts(Path(root) / "artifacts"), "")

    def prepare_query(self, query):
        self.adapter.original_goal = query
        return self.adapter.filter_context(query, source="user_input")

    def system_prompt_transform(self, prompt):
        return self.adapter.augment_system_prompt(prompt)

    def on_pre_tool_call(self, ctx):
        self.adapter.registry = ctx.metadata["available_tools"]
        decision = self.adapter.check_action(ctx.tool_name, ctx.arguments, None)
        if decision.blocked:
            warnings = self.adapter.runtime.runtime_events.before_model(self.adapter.state)
            self.adapter.delivered_warnings.extend(warnings)
            raise PermissionError("\n".join([decision.reason, *warnings]))

    def on_post_tool_call(self, ctx, result):
        if result.exception is not None:
            return result
        # The trusted bridge serializes native outputs before crossing the RPC.
        if not isinstance(result.raw, str):
            raise TypeError('SHE observations must be serialized text')
        text = result.raw
        if result.is_error:
            # Failed calls are observations, not successful executions.
            self.adapter._pending_tool_call = None
        result.raw = self.adapter.filter_context(text, source="tool_output")
        return result

    def finalize_response(self, text):
        return self.adapter.finalize_response(text)

    def export_state(self):
        return {"she_revision": SHE_REVISION, "selective_judge": "conservative_fallback",
                **self.adapter.export_state()}
