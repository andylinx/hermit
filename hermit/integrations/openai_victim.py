"""OpenAI-compatible victims for AgentDyn, including NVIDIA inference endpoints.

An api_script is parsed, never imported or executed: only literal OpenAI client
settings (or simple environment-variable lookups) are read. Keys remain in memory.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import time


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


def make_victim(params: dict, base: Path, on_call=None):
    from openai import OpenAI
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.agent_pipeline.llms.openai_llm import (
        _function_to_openai, _message_to_openai, _openai_to_assistant_message,
    )

    settings = script_settings(base / Path(params["api_script"]).expanduser()) if params.get("api_script") else {}
    if params.get("base_url"):
        settings["base_url"] = params["base_url"]
    if params.get("api_key_env"):
        settings["api_key"] = os.environ.get(params["api_key_env"])
    if not settings.get("base_url") or not settings.get("api_key"):
        raise ValueError("victim needs base_url and api_key_env, or an api_script with OpenAI settings")
    client = OpenAI(**settings, timeout=float(params.get("request_timeout_s", 120)),
                    max_retries=int(params.get("max_retries", 1)))

    class CompatibleVictim(BasePipelineElement):
        name = params["model"]

        def __init__(self):
            self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0}

        def close(self):
            client.close()

        def query(self, query, runtime, env, messages=(), extra_args=None):
            request = {"model": self.name, "messages": [_message_to_openai(m, self.name) for m in messages],
                       "temperature": float(params.get("temperature", 0.0)),
                       "max_tokens": int(params.get("max_tokens", 4096))}
            tools = [_function_to_openai(tool) for tool in runtime.functions.values()]
            if tools:
                request.update(tools=tools, tool_choice="auto")
            if params.get("top_p") is not None:
                request["top_p"] = float(params["top_p"])
            if params.get("extra_body"):
                request["extra_body"] = params["extra_body"]
            started = time.monotonic()
            try:
                completion = client.chat.completions.create(**request)
            except Exception as exc:
                # A failed request may have consumed provider tokens even though
                # no usage response arrived; exact episode cost is then unknown.
                self.usage["calls"] += 1
                self.usage["unknown_usage_calls"] += 1
                if on_call is not None:
                    on_call({"status": "error", "type": type(exc).__name__,
                             "http_status": getattr(exc, "status_code", None),
                             "usage": dict(self.usage),
                             "wall_s": time.monotonic() - started})
                # SDK errors can include request bodies. Keep credentials and
                # prompts out of exception reports forwarded to the learner.
                raise RuntimeError(f"victim API failed: {type(exc).__name__}, HTTP {getattr(exc, 'status_code', None)}") from None
            self.usage["calls"] += 1
            if completion.usage is None:
                self.usage["unknown_usage_calls"] += 1
            else:
                self.usage["input_tokens"] += completion.usage.prompt_tokens
                self.usage["output_tokens"] += completion.usage.completion_tokens
            if on_call is not None:
                on_call({"status": "ok", "call": self.usage["calls"],
                         "wall_s": time.monotonic() - started, "usage": dict(self.usage),
                         "finish_reason": completion.choices[0].finish_reason if completion.choices else None})
            if not completion.choices or completion.choices[0].finish_reason in {"length", "content_filter"}:
                raise RuntimeError("victim response was empty, truncated or filtered")
            message = completion.choices[0].message
            output = _openai_to_assistant_message(message)
            # Upstream silently drops malformed tool calls. Reject those episodes
            # instead of mistaking a parser failure for a secure final response.
            if len(output.get("tool_calls") or []) != len(message.tool_calls or []):
                raise RuntimeError("victim returned malformed tool-call arguments")
            return query, runtime, env, [*messages, output], extra_args or {}

    return CompatibleVictim()
