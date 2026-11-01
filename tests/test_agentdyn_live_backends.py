"""Backend contract tests; no API calls or Codex processes are started here."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermit.integrations.openai_victim import script_settings


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
    from hermit.integrations.openai_victim import make_victim
    monkeypatch.setenv("VICTIM_TEST_KEY", "dummy-secret")
    requests = []
    response = {"id": "test", "created": 0, "object": "chat.completion", "model": "nemotron-test",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ready"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}

    def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 2:
            raise RuntimeError("private request: dummy-secret")
        return ChatCompletion.model_validate(response)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
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


def test_codex_proposal_command_schema_and_usage(tmp_path, monkeypatch):
    from hermit.algorithms.evolvers.evosafe import codex
    scratch, output = tmp_path / "scratch", tmp_path / "output"
    scratch.mkdir()
    output.mkdir()
    ctx = SimpleNamespace(workspace=SimpleNamespace(scratch=scratch, output=output),
                          params={}, sandbox=None, cancel=None)
    proposal = {"summary": "fixture", "files": {"ADAPTER.md": "policy", "defense.py": "code", "BUNDLE.md": "notes"}}

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            assert command[:3] == ["codex", "exec", "--yolo"]
            assert command[-1] == "-"
            assert "Do not read other project files" in kwargs["stdin"].read()
            schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
            assert schema["properties"]["files"]["additionalProperties"] is False
            Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(proposal))
            kwargs["stdout"].write(json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 20, "cached_input_tokens": 5, "output_tokens": 10}}) + "\n")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(codex.subprocess, "Popen", Process)
    response, usage, error = codex.propose(ctx, [{"role": "user", "content": "inert fixture"}])
    assert error is None and json.loads(response["content"]) == proposal
    assert usage[0].input_tokens == 20 and usage[0].output_tokens == 10


@pytest.mark.parametrize("malformed", [False, True])
def test_compatible_victim_rejects_partial_responses(tmp_path, monkeypatch, malformed):
    openai = pytest.importorskip("openai")
    pytest.importorskip("agentdojo")
    from openai.types.chat import ChatCompletion
    from hermit.integrations.openai_victim import make_victim
    monkeypatch.setenv("VICTIM_TEST_KEY", "dummy")
    message = {"role": "assistant", "content": None}
    if malformed:
        message["tool_calls"] = [{"id": "call", "type": "function",
                                  "function": {"name": "echo", "arguments": "not json"}}]
    response = ChatCompletion.model_validate({"id": "test", "created": 0, "object": "chat.completion",
        "model": "nemotron-test", "choices": [{"index": 0, "finish_reason": "tool_calls" if malformed else "length",
                                                  "message": message}], "usage": None})
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)),
                             close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    victim = make_victim({"model": "nemotron-test", "base_url": "https://example.invalid",
                          "api_key_env": "VICTIM_TEST_KEY"}, tmp_path)
    with pytest.raises(RuntimeError, match="malformed" if malformed else "truncated"):
        victim.query("task", SimpleNamespace(functions={}), {})
    assert victim.usage["unknown_usage_calls"] == 1


def test_check_respects_and_restores_disabled_sandbox(tmp_path, monkeypatch):
    import yaml
    from hermit.config import Config
    from hermit import settings_check, spec
    from hermit.spec import CheckResult
    root = Path(__file__).resolve().parents[1]
    config_path = root / "examples/agentdyn/nvidia-smoke.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["template"] = str(root / "hermit/algorithms/templates/evosafe")
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(spec, "SANDBOX_ENFORCE", "required")
    seen = []

    def check(*args):
        seen.append(spec.SANDBOX_ENFORCE)
        return CheckResult(True)

    monkeypatch.setattr(settings_check, "check_spec", check)
    settings_check.run_check(Config.load(path), probe=False, log=lambda *args: None)
    assert seen == [None]
    assert spec.SANDBOX_ENFORCE == "required"
