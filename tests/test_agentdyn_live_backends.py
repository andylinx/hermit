"""Backend contract tests; no API calls or Codex processes are started here."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples/agentdyn/utils"))  # bridge, victim, auditor
from victim import model_params, script_settings


def test_model_backend_uses_local_connection_settings(tmp_path, monkeypatch):
    import yaml
    from hermit.config import Config

    local = tmp_path / "backends.yaml"
    local.write_text(yaml.safe_dump({"vllm": {
        "base_url": "https://model-service.example.invalid/v1", "api_key_env": "VICTIM_TEST_KEY",
        "key_required": True, "apis": ["chat"],
        "models": {"nvidia/llama-3.3-nemotron-super-49b-v1.5": "provider/nemotron"},
        "prices": {"provider/nemotron": {"input": 1, "output": 2}}, "extra_body": {"top_k": 50},
    }}))
    monkeypatch.setenv("HA_BACKENDS", str(local))
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    root = Path(__file__).resolve().parents[1]
    config = Config.load(root / "examples/agentdyn/evosafe/run_nemotron_claude.yaml")
    original = config["agent"]["params"]
    params = model_params({**original, "extra_body": {"top_k": 20}})
    assert params["model"] == "provider/nemotron"
    assert params["base_url"] == "https://model-service.example.invalid/v1"
    assert params["api_key_env"] == "VICTIM_TEST_KEY" and params["key_required"]
    assert params["price"] == {"input": 1, "output": 2}
    assert params["extra_body"] == {"top_k": 20}
    assert isinstance(original["model"], dict)  # Adapter does not mutate the loaded config.


def test_api_script_is_parsed_without_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("VICTIM_TEST_KEY", "dummy-secret")
    script = tmp_path / "api.py"
    script.write_text('''
import os
from openai import OpenAI
URL = "https://example.invalid/v1"
KEY = os.environ["VICTIM_TEST_KEY"]
client = OpenAI(base_url=URL, api_key=KEY)
raise RuntimeError("must not execute this module")
''')
    assert script_settings(script) == {"base_url": "https://example.invalid/v1", "api_key": "dummy-secret"}
    script.write_text('client = OpenAI(base_url=compute_url(), api_key="dummy")')
    with pytest.raises(ValueError, match="literals"):
        script_settings(script)


def test_compatible_victim_tools_usage_and_error_redaction(tmp_path, monkeypatch):
    openai = pytest.importorskip("openai")
    pytest.importorskip("agentdojo")
    from openai.types.chat import ChatCompletion
    from victim import make_victim
    monkeypatch.setenv("VICTIM_TEST_KEY", "dummy-secret")
    requests = []
    response = {"id": "test", "created": 0, "object": "chat.completion", "model": "nemotron-test",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ready"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}

    def create(self, messages, **kwargs):
        requests.append(kwargs)
        if len(requests) == 2:
            raise RuntimeError("private request: dummy-secret")
        from hermit.agent.model.usage import Usage
        return {"content": "ready", "_response": response}, Usage("nemotron-test", input_tokens=10, output_tokens=2, calls=1)

    monkeypatch.setattr("hermit.agent.model.llm.ChatClient.chat", create)
    events = []
    victim = make_victim({"model": "nemotron-test", "base_url": "https://example.invalid/v1",
                          "api_key_env": "VICTIM_TEST_KEY", "max_tokens": 123}, tmp_path, on_call=events.append)
    out = victim.query("hi", SimpleNamespace(functions={}), {}, messages=[])
    assert out[3][-1]["content"][0]["content"] == "ready"
    assert requests[0]["max_tokens"] == 123
    assert "tools" not in requests[0]
    assert victim.usage == {"calls": 1, "input_tokens": 10, "output_tokens": 2, "unknown_usage_calls": 0}
    with pytest.raises(RuntimeError, match="victim API failed") as error:
        victim.query("hi", SimpleNamespace(functions={}), {})
    assert "dummy-secret" not in str(error.value)
    assert events[0]["finish_reason"] == "stop" and events[1]["status"] == "error"
    assert victim.usage["calls"] == 2 and victim.usage["unknown_usage_calls"] == 1
    assert "dummy-secret" not in json.dumps(events)
    victim.close()


@pytest.mark.parametrize("failure", ["truncated", "malformed", "textual"])
def test_compatible_victim_rejects_partial_responses(tmp_path, monkeypatch, failure):
    openai = pytest.importorskip("openai")
    pytest.importorskip("agentdojo")
    from openai.types.chat import ChatCompletion
    from victim import make_victim
    monkeypatch.setenv("VICTIM_TEST_KEY", "dummy")
    message = {"role": "assistant", "content": "<TOOLCALL>invalid</TOOLCALL>" if failure == "textual" else None}
    if failure == "malformed":
        message["tool_calls"] = [{"id": "call", "type": "function",
                                  "function": {"name": "echo", "arguments": "not json"}}]
    response = ChatCompletion.model_validate({"id": "test", "created": 0, "object": "chat.completion",
        "model": "nemotron-test", "choices": [{"index": 0, "message": message,
        "finish_reason": "length" if failure == "truncated" else "tool_calls" if failure == "malformed" else "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15} if failure == "textual" else None})
    from hermit.agent.model.usage import Usage
    monkeypatch.setattr("hermit.agent.model.llm.ChatClient.chat", lambda self, messages, **kw:
                        ({"_response": response.model_dump()}, Usage("nemotron-test")))
    events = []
    victim = make_victim({"model": "nemotron-test", "base_url": "https://example.invalid/v1",
                          "api_key_env": "VICTIM_TEST_KEY"}, tmp_path, events.append)
    with pytest.raises(RuntimeError, match="truncated" if failure == "truncated" else "malformed" if failure == "malformed" else "unparsed_textual_tool_call"):
        victim.query("task", SimpleNamespace(functions={}), {})
    assert victim.usage["calls"] == 1 and len(events) == 1
    if failure == "textual":
        assert victim.usage["input_tokens"] == 10 and victim.usage["output_tokens"] == 5
        assert events[0]["status"] == "error"
    else:
        assert victim.usage["unknown_usage_calls"] == 1


@pytest.mark.parametrize('content,calls,expected', [
    ('Done.', False, None),
    ('<think>private reasoning</think>Done.', False, None),
    ('<think>unfinished', False, 'unfinished_reasoning'),
    ('<think>complete</think>', False, 'missing_terminal_answer'),
    ('<TOOLCALL>{invalid}</TOOLCALL>', False, 'unparsed_textual_tool_call'),
    (None, False, 'missing_terminal_answer'),
    (None, True, None),
    ([{'type': 'text', 'text': 'Done.'}], False, None),
])
def test_terminal_protocol_validation(content, calls, expected):
    from victim import terminal_protocol_error
    assert terminal_protocol_error(content, calls) == expected


def test_victim_uses_direct_and_preserves_wire_request(tmp_path, monkeypatch):
    """Exercise the real direct + ChatClient path against a loopback provider."""
    pytest.importorskip("agentdojo")
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from hermit.agent.base import interface
    from victim import make_victim
    seen, bases = [], []
    original = interface.make
    def make(name, settings, model):
        bases.append(name)
        return original(name, settings, model)
    monkeypatch.setattr(interface, "make", make)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            seen.append((self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = json.dumps({"id": "fixture", "created": 0, "object": "chat.completion", "model": "fixture",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ready"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("VICTIM_FIXTURE_KEY", "fixture-key")
    try:
        victim = make_victim({"model": "fixture", "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                              "api_key_env": "VICTIM_FIXTURE_KEY", "max_tokens": 41, "top_p": 0.8,
                              "extra_body": {"reasoning_effort": "low"}}, tmp_path)
        victim.query("", SimpleNamespace(functions={}), {}, messages=[])
        victim.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert bases == ["direct"]
    key, body = seen[0]
    assert key == "Bearer fixture-key"
    assert body["model"] == "fixture" and body["max_tokens"] == 41 and body["top_p"] == 0.8
    assert body["reasoning_effort"] == "low" and "extra_body" not in body and "tools" not in body
    assert victim.usage["input_tokens"] == 5 and victim.usage["output_tokens"] == 2
