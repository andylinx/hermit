"""Structured Codex CLI proposals, with cancellation and no repository mutation."""
import json
import os
import signal
import subprocess
import time

from hermit.agent.base.records import parse_log, price_usage


def proposal_schema():
    return {"type": "object", "additionalProperties": False, "required": ["summary", "files"],
              "properties": {"summary": {"type": "string"}, "files": {
                  "type": "object", "additionalProperties": False,
                  "required": ["ADAPTER.md", "defense.py", "BUNDLE.md"],
                  "properties": {name: {"type": "string"} for name in ("ADAPTER.md", "defense.py", "BUNDLE.md")}}}}


def propose(ctx, messages):
    return call_role(ctx, messages, proposal_schema(), "proposal")


def safety_refused(log):
    for line in log.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') not in ('error', 'turn.failed'):
            continue
        error = event.get('error') or {}
        text = str(event.get('message') or (error.get('message') if isinstance(error, dict) else error)).lower()
        if 'flagged for possible cybersecurity risk' in text or 'content_policy_violation' in text:
            return True
    return False


def call_role(ctx, messages, schema, name):
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError("invalid role artifact name")
    root = ctx.workspace.scratch / ("codex-" + name)
    root.mkdir()
    schema_path, answer = root / "schema.json", ctx.workspace.output / ("codex-" + name + ".json")
    schema_path.write_text(json.dumps(schema))
    prompt = root / "prompt.txt"
    prompt.write_text("Perform only the requested defensive role from the supplied evidence. "
                      "Do not read other project files, invoke APIs, execute shell commands, edit files, "
                      "or perform any git operations. All required information is below.\n" + json.dumps(messages))
    log = ctx.workspace.output / ("codex-events.jsonl" if name == "proposal" else "codex-" + name + "-events.jsonl")
    command = [ctx.params.get("codex_bin", "codex"), "exec", "--yolo", "--json", "--ephemeral",
               "--skip-git-repo-check", "-C", str(root), "--output-schema", str(schema_path),
               "--output-last-message", str(answer)]
    if ctx.params.get("codex_model"):
        command += ["--model", ctx.params["codex_model"]]
    command += ["-"]
    env = dict(os.environ)
    if ctx.sandbox is not None:
        command, env = ctx.sandbox.wrap(command, env=env)
    timeout = float(ctx.params.get("codex_timeout_s", 600))
    started = time.monotonic()
    with prompt.open() as stdin, log.open("w") as stdout:
        proc = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=subprocess.STDOUT,
                                cwd=root, env=env, start_new_session=True)
        reason = None
        try:
            while proc.poll() is None:
                if ctx.cancel is not None and ctx.cancel.is_set():
                    reason = "Codex proposal cancelled"
                    break
                if time.monotonic() - started > timeout:
                    reason = "Codex proposal timed out"
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
    _, usage = parse_log(log, "codex", ctx.params.get("codex_model") or "codex")
    price_usage(usage, ctx.params)
    if proc.returncode != 0 and safety_refused(log):
        return None, usage, 'SAFETY_REVIEW_REFUSAL: provider security review rejected the role request'
    if reason or proc.returncode != 0 or not answer.is_file():
        return None, usage, reason or f"Codex exited {proc.returncode}; inspect {log.name}"
    return {"content": answer.read_text()}, usage, None
