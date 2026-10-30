"""Structured Codex CLI proposals, with cancellation and no repository mutation."""
import json
import os
import signal
import subprocess
import time

from hermit.evolver.agent import parse_log, price_usage


def propose(ctx, messages):
    root = ctx.workspace.scratch / "codex-proposal"
    root.mkdir()
    schema = {"type": "object", "additionalProperties": False, "required": ["summary", "files"],
              "properties": {"summary": {"type": "string"}, "files": {
                  "type": "object", "additionalProperties": False,
                  "required": ["ADAPTER.md", "defense.py", "BUNDLE.md"],
                  "properties": {name: {"type": "string"} for name in ("ADAPTER.md", "defense.py", "BUNDLE.md")}}}}
    schema_path, answer = root / "schema.json", ctx.workspace.output / "codex-proposal.json"
    schema_path.write_text(json.dumps(schema))
    prompt = root / "prompt.txt"
    prompt.write_text("Produce only the requested defense proposal from the supplied evidence. "
                      "Do not read other project files, invoke APIs, execute shell commands, edit files, "
                      "or perform any git operations. All required information is below.\n" + json.dumps(messages))
    log = ctx.workspace.output / "codex-events.jsonl"
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
    if reason or proc.returncode != 0 or not answer.is_file():
        return None, usage, reason or f"Codex exited {proc.returncode}; inspect codex-events.jsonl"
    return {"content": answer.read_text()}, usage, None
