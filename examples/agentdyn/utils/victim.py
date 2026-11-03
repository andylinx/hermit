"""OpenAI-compatible victims for AgentDyn, using Hermit's model backend settings.

An api_script is parsed, never imported or executed: only literal OpenAI client
settings (or simple environment-variable lookups) are read. Keys remain in memory.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
import time


def terminal_protocol_error(content, has_tool_calls=False):
    """Recognize non-terminal protocol output without executing textual calls."""
    if has_tool_calls:
        return None
    if isinstance(content, list):
        content = '\n'.join(part.get('text', part.get('content', '')) for part in content
                            if isinstance(part, dict) and isinstance(part.get('text', part.get('content')), str))
    text = content if isinstance(content, str) else ''
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if text.startswith('<think>'):
        return 'unfinished_reasoning'
    if not text:
        return 'missing_terminal_answer'
    if text.startswith('<TOOLCALL>'):
        return 'unparsed_textual_tool_call'
    return None


def script_settings(path: Path) -> dict:
    tree = ast.parse(path.expanduser().read_text())
    values = {}

    def read(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and ast.unparse(node.func) in {"os.getenv", "os.environ.get"}):
            args = [read(arg) for arg in node.args]
            return os.getenv(*args)
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            return os.environ[read(node.slice)]
        raise ValueError("api_script settings must be literals or environment-variable references")

    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = read(node.value)
            except ValueError:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = value
    clients = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and ast.unparse(n.func) in {"OpenAI", "openai.OpenAI"}]
    if len(clients) != 1:
        raise ValueError("api_script must contain exactly one OpenAI(...) client")
    return {kw.arg: read(kw.value) for kw in clients[0].keywords if kw.arg in {"base_url", "api_key"}}


def model_params(params: dict) -> dict:
    """Adapt a model spec resolved by Config to the victim's existing client settings."""
    if not isinstance(params.get("model"), dict):
        return params
    from hermit.agent.model.backends import Binding
    binding = Binding.from_spec(params["model"])
    return {**params, "model": binding.model, "base_url": binding.base_url,
            "api_key_env": binding.api_key_env, "key_required": binding.backend.key_required,
            "price": params.get("price") if params.get("price") is not None else binding.price,
            "extra_body": {**binding.extra_body, **(params.get("extra_body") or {})}}


def make_victim(params: dict, base: Path, on_call=None):
    from hermit.agent.model.backends import PLACEHOLDER_KEY
    from openai.types.chat import ChatCompletion
    from hermit.agent.base.interface import make
    from hermit.agent.model.llm import ChatClient
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.agent_pipeline.llms.openai_llm import (
        _function_to_openai, _message_to_openai, _openai_to_assistant_message,
    )

    if params.get("base", "direct") != "direct":
        raise ValueError("AgentDyn uses agent.base: direct for each native model turn")
    params = model_params(params)
    settings = script_settings(base / Path(params["api_script"]).expanduser()) if params.get("api_script") else {}
    if params.get("base_url"):
        settings["base_url"] = params["base_url"]
    if params.get("api_key_env"):
        settings["api_key"] = os.environ.get(params["api_key_env"])
    if not settings.get("base_url") or (params.get("key_required", True) and not settings.get("api_key")):
        raise ValueError("victim needs a configured model backend, or base_url and api_key_env (or api_script)")
    settings["api_key"] = settings.get("api_key") or PLACEHOLDER_KEY
    client = ChatClient(settings["base_url"], params["model"], price=params.get("price"),
                        timeout=float(params.get("request_timeout_s", 120)),
                        max_retries=int(params.get("max_retries", 1)), extra_body=params.get("extra_body"))
    agent = make("direct", {}, client)
    headers = {"Authorization": "Bearer " + settings["api_key"]}

    class CompatibleVictim(BasePipelineElement):
        name = params["model"]

        def __init__(self):
            self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0}

        def close(self):
            pass  # ChatClient closes the connection after every call.

        def query(self, query, runtime, env, messages=(), extra_args=None):
            request = {"model": self.name, "messages": [_message_to_openai(m, self.name) for m in messages],
                       "temperature": float(params.get("temperature", 0.0)),
                       "max_tokens": int(params.get("max_tokens", 4096))}
            tools = [_function_to_openai(tool) for tool in runtime.functions.values()]
            if tools:
                request.update(tools=tools, tool_choice="auto")
            if params.get("top_p") is not None:
                request["top_p"] = float(params["top_p"])
            started = time.monotonic()
            try:
                history = request.pop("messages")
                offered = request.pop("tools", ())
                choice = request.pop("tool_choice", None)
                result = agent.configured(tool_choice=choice, request={**request, "extra_headers": headers,
                                          "return_response": True}).run(history, tools=offered)
                completion = ChatCompletion.model_validate(result.extra["message"]["_response"])
            except Exception as exc:
                # A failed request may have consumed provider tokens even though
                # no usage response arrived; exact episode cost is then unknown.
                self.usage["calls"] += 1
                self.usage["unknown_usage_calls"] += 1
                if on_call is not None:
                    on_call({"status": "error", "type": type(exc).__name__,
                             "http_status": getattr(exc, "code", None),
                             "usage": dict(self.usage),
                             "wall_s": time.monotonic() - started})
                # Provider errors can include request bodies. Keep credentials and
                # prompts out of exception reports forwarded to the learner.
                raise RuntimeError(f"victim API failed: {type(exc).__name__}, HTTP {getattr(exc, 'code', None)}") from None
            self.usage["calls"] += 1
            if completion.usage is None:
                self.usage["unknown_usage_calls"] += 1
            else:
                self.usage["input_tokens"] += completion.usage.prompt_tokens
                self.usage["output_tokens"] += completion.usage.completion_tokens
            message = completion.choices[0].message if completion.choices else None
            protocol_error = terminal_protocol_error(message.content, bool(message.tool_calls)) if message else 'empty_response'
            if on_call is not None:
                on_call({"status": "error" if protocol_error else "ok", "call": self.usage["calls"],
                         "protocol_error": protocol_error,
                         "wall_s": time.monotonic() - started, "usage": dict(self.usage),
                         "finish_reason": completion.choices[0].finish_reason if completion.choices else None})
            if not completion.choices or completion.choices[0].finish_reason in {"length", "content_filter"}:
                raise RuntimeError("victim response was empty, truncated or filtered")
            if protocol_error:
                raise RuntimeError(f"victim terminal protocol error: {protocol_error}")
            message = completion.choices[0].message
            output = _openai_to_assistant_message(message)
            # Upstream silently drops malformed tool calls. Reject those episodes
            # instead of mistaking a parser failure for a secure final response.
            if len(output.get("tool_calls") or []) != len(message.tool_calls or []):
                raise RuntimeError("victim returned malformed tool-call arguments")
            return query, runtime, env, [*messages, output], extra_args or {}

    return CompatibleVictim()
