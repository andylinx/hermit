"""Structured Claude Code CLI role calls: no tools, no session, cancellation, same contract as codex.call_role."""
import json
import os
import signal
import subprocess
import time

from hermit.agent.base.records import parse_log


def refused(event):
    """A model or policy refusal of the role request (stop, never retried automatically)."""
    text = str(event.get('result') or '').lower()
    return (event.get('stop_reason') == 'refusal' or 'usage policy' in text
            or 'content_policy_violation' in text or 'flagged for possible cybersecurity risk' in text)


def call_role(ctx, messages, schema, name):
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError("invalid role artifact name")
    root = ctx.workspace.scratch / ("claude-" + name)
    root.mkdir()
    prompt = root / "prompt.txt"
    # The role text goes in the system prompt; the evidence payload is the user turn.
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    prompt.write_text("Perform only the requested defensive role from the supplied evidence. "
                      "All required information is below; answer with the structured result only.\n" + user)
    log = ctx.workspace.output / ("claude-" + name + "-events.json")
    # --tools "": the role cannot read files, run commands or browse; it only answers from the prompt.
    command = [ctx.params.get("claude_bin", "claude"), "-p", "--output-format", "json",
               "--json-schema", json.dumps(schema), "--tools", "", "--no-session-persistence",
               "--append-system-prompt", system]
    if ctx.params.get("claude_model"):
        command += ["--model", ctx.params["claude_model"]]
    env = dict(os.environ)
    if ctx.sandbox is not None:
        command, env = ctx.sandbox.wrap(command, env=env)
    timeout = float(ctx.params.get("claude_timeout_s", 1200))
    started = time.monotonic()
    with prompt.open() as stdin, log.open("w") as stdout:
        proc = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=subprocess.STDOUT,
                                cwd=root, env=env, start_new_session=True)
        reason = None
        try:
            while proc.poll() is None:
                if ctx.cancel is not None and ctx.cancel.is_set():
                    reason = "Claude Code role cancelled"
                    break
                if time.monotonic() - started > timeout:
                    reason = "Claude Code role timed out"
                    break
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
    _, usage = parse_log(log, "claude", ctx.params.get("claude_model") or "claude")
    if reason:
        return None, usage, reason
    try:
        event = json.loads(log.read_text())
    except ValueError:
        return None, usage, f"Claude Code exited {proc.returncode} without a result; inspect {log.name}"
    if refused(event):
        return None, usage, 'SAFETY_REVIEW_REFUSAL: the model refused the role request'
    answer = event.get("structured_output")
    if proc.returncode != 0 or event.get("is_error") or not isinstance(answer, dict):
        return None, usage, f"Claude Code failed ({event.get('subtype')}, {event.get('stop_reason')}); inspect {log.name}"
    (ctx.workspace.output / ("claude-" + name + ".json")).write_text(json.dumps(answer, indent=2))
    return {"content": json.dumps(answer)}, usage, None
