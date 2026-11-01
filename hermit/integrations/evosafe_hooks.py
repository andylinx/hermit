"""Portable EvoSafe runtime hook contract, explicitly separate from DTAP imports.

Subclass Defense to opt into structured hooks. The legacy dictionary hooks remain
supported by AgentDyn for existing adapters. Context contains public tool schemas
and trusted task intent, never benchmark labels, hidden state or judge predicates.
"""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolCallContext:
    framework: str
    server: str
    tool_name: str
    arguments: dict
    trace_id: str | None = None
    metadata: dict = field(default_factory=dict)
    classify_output: Callable[[str], dict] | None = field(default=None, repr=False, compare=False)


@dataclass
class ToolCallResult:
    raw: Any = None
    is_error: bool = False
    duration: float = 0.0
    exception: BaseException | None = None
    # AgentDyn normally catches tool exceptions and returns only their text.
    # Preserve that text without inventing an exception type.
    error: str | None = None


class Defense:
    hook_api = "structured-v1"

    def system_prompt_transform(self, prompt):
        return prompt

    def on_pre_tool_call(self, ctx):
        return None

    def on_post_tool_call(self, ctx, result):
        return None
