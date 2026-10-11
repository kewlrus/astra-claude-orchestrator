#!/usr/bin/env python3
"""Run one local Claude Code phase, preserving evidence and resumable identity."""

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid


MODEL = "claude-opus-5-5"
HEARTBEAT_SECONDS = 5.0
REQUEST_FIELDS = ("id", "command", "cwd", "reason", "expected_effects")
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready_for_review", "needs_permission", "blocked", "failed"]},
        "summary": {"type": "string"},
        **{key: {"type": "array", "items": {"type": "string"}}
           for key in ("changed_files", "verification", "limitations")},
        "permission_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {key: {"type": "string", "minLength": 1} for key in REQUEST_FIELDS},
                "required": list(REQUEST_FIELDS),
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "summary", "changed_files", "verification", "limitations", "permission_requests"],
    "additionalProperties": False,
}
INSTRUCTIONS = """You implement one phase for Astra, who owns planning and acceptance.
Follow the brief and applicable project guidance. You are not alone in the workspace:
preserve pre-existing edits and do not edit coordinator-owned planning/run artifacts.
Own in-scope discovery, implementation, testing and debugging. Do not spawn agents,
invoke another coding CLI, or delegate through skills, shell commands or MCP.
Do not commit, stage, push, deploy, change providers or expand permissions.
If a needed command lacks permission, ask Astra: return status needs_permission
and a permission_requests entry with a unique id, the exact command, absolute cwd,
reason, and expected_effects (files changed/deleted, network, external effects).
Request before execution when the gap is known. After a denial, do not retry it,
hide it inside a script/interpreter, or change policy. Save your checkpoint and
return promptly so Astra can decide; do not wait or poll for a reply in the child.
You may batch already-known requests. Never include credentials or secrets.
Astra may resume this same session with approved process-local rules, an
alternative, or a refusal. Approval is not automatic and cannot override host
or managed policy. The requested command must not run until authorized.
If blocked, stop and report the concrete blocker. Do not claim acceptance.
If the brief requests a full task-report, write it to its assigned task-owned path
outside runner artifacts. Leave any Astra-only review record for Astra.
Return the requested structured report: status ready_for_review, needs_permission,
blocked or failed,
summary, changed_files, verification (commands, outcomes and evidence paths),
limitations, permission_requests (empty when none). Include checks you could not
run. Empty evidence is not passing tests.
"""


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def lock_root(workspace):
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve()
    return workspace


def read_result(path, session_id):
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("type") != "result":
        raise ValueError("expected a Claude result object")
    if result.get("session_id") != session_id:
        raise ValueError("result session ID does not match requested session")
    return result


def failure_details(result, exit_code):
    """Classify CLI failure without forwarding its free-text output."""
    if exit_code < 0:
        return {"failure_kind": "signal", "api_status": None}
    failed = exit_code != 0 or result.get("is_error") is not False
    api_status = result.get("api_error_status")
    if type(api_status) is not int or not 100 <= api_status <= 599:
        api_status = None
    kind = None
    if failed:
        if api_status == 429:
            kind = "api_rate_limit"
        elif api_status in (401, 403):
            kind = "api_auth"
        elif api_status is not None or result.get("terminal_reason") == "api_error":
            kind = "api_error"
        elif result.get("subtype") == "error_max_budget_usd":
            kind = "budget_limit"
        elif result.get("subtype") == "error_max_turns":
            kind = "turn_limit"
        else:
            kind = "cli_exit" if exit_code else "cli_error"
    return {"failure_kind": kind, "api_status": api_status if failed else None}


def read_report(result):
    if result.get("is_error") is not False or result.get("subtype") != "success":
        raise ValueError("Claude reported a non-success result; inspect stdout.json")
    report = result.get("structured_output")
    if not isinstance(report, dict) or set(report) != set(SCHEMA["required"]):
        raise ValueError("missing or invalid structured report fields")
    if report["status"] not in ("ready_for_review", "needs_permission", "blocked", "failed"):
        raise ValueError("invalid report status")
    if not isinstance(report["summary"], str) or not report["summary"].strip():
        raise ValueError("report summary must be nonempty text")
    for key in ("changed_files", "verification", "limitations"):
        if not isinstance(report[key], list) or not all(isinstance(v, str) for v in report[key]):
            raise ValueError("invalid report list: " + key)
    requests = report["permission_requests"]
    if not isinstance(requests, list):
        raise ValueError("permission_requests must be a list")
    ids = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != set(REQUEST_FIELDS):
            raise ValueError("invalid permission request fields")
        if not all(isinstance(v, str) and v.strip() for v in request.values()):
            raise ValueError("permission request fields must be nonempty text")
        if not Path(request["cwd"]).is_absolute() or request["id"] in ids:
            raise ValueError("permission request needs absolute cwd and unique id")
        ids.add(request["id"])
    if report["status"] == "needs_permission" and not requests and not result.get("permission_denials"):
        raise ValueError("needs_permission requires a request or a CLI denial")
    return report


def wait_for_cli(proc, metadata, run_dir, timeout):
    """Observe the child locally; no heartbeat goes to stdout or the model."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        metadata.update(process_state="running", heartbeat_at=time.time())
        write_json(run_dir / "metadata.json", metadata)
        interval = HEARTBEAT_SECONDS
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            interval = min(interval, remaining)
        try:
            return proc.wait(timeout=interval)
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                raise


def terminate_group(proc):
    deadline = time.monotonic() + 5
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise PermissionError("process-group SIGTERM denied") from exc
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(max(0, deadline - time.monotonic()))
    # Reap the child before addressing remaining descendants. Avoid signal-0
    # probes, which can return EPERM for a dying group on macOS.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                        default="medium", help="Claude effort (default: medium; override only on user request)")
    parser.add_argument("--allow-tool", action="append", default=[])
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=positive)
    parser.add_argument("--max-budget-usd", type=positive)
    parser.add_argument("--claude-bin", default="claude")
    args = parser.parse_args()
    workspace, run_dir = args.workspace.resolve(), args.run_dir.resolve()
    if not workspace.is_dir():
        raise ValueError("workspace is not a directory")
    if not args.model.strip() or args.model.startswith("-"):
        raise ValueError("invalid model")
    executable = shutil.which(args.claude_bin)
    if not executable:
        raise ValueError("Claude Code executable not found")
    executable = str(Path(executable).resolve())
    brief = args.brief.read_text(encoding="utf-8")
    if not brief.strip():
        raise ValueError("brief is empty")
    session_id = str(uuid.uuid4())
    if args.resume_from:
        prior = json.loads((args.resume_from / "metadata.json").read_text(encoding="utf-8"))
        if prior.get("workspace") != str(workspace) or prior.get("model") != args.model:
            raise ValueError("resume workspace/model does not match the previous run")
        session_id = str(uuid.UUID(prior["session_id"]))

    allowed = ["Read", "Glob", "Grep"]
    if not args.read_only:
        allowed += ["Edit", "Write"]
    allowed += args.allow_tool
    cmd = [executable, "-p", "--model", args.model, "--output-format", "json",
           "--json-schema", json.dumps(SCHEMA), "--permission-mode", "dontAsk",
           "--permission-prompts", "none", "--disallowedTools",
           "Agent,Task,Edit,Write" if args.read_only else "Agent,Task",
           "--allowedTools", ",".join(allowed),
           "--resume" if args.resume_from else "--session-id", session_id]
    cmd += ["--effort", args.effort]
    if args.max_budget_usd:
        cmd += ["--max-budget-usd", str(args.max_budget_usd)]

    # Keep this inode stable; unlinking advisory locks permits concurrent writers.
    with (lock_root(workspace) / ".astra-claude.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another runner owns this workspace") from exc
        run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        prompt = run_dir / "prompt.md"
        permission_context = (
            "\n## Invocation permissions\n\n"
            "Runner-supplied allow rules (existing CLI/host restrictions still apply):\n"
            + json.dumps(allowed) + "\nWorkspace: " + str(workspace) + "\n"
        )
        prompt.write_text(INSTRUCTIONS + permission_context + "\n## Phase brief\n\n" + brief,
                          encoding="utf-8")
        metadata = {
            "workspace": str(workspace), "model": args.model, "session_id": session_id,
            "resume_from": str(args.resume_from.resolve()) if args.resume_from else None,
            "started_at": time.time(), "status": "running", "command": cmd,
            "runner_pid": os.getpid(), "claude_exit_code": None,
            "process_state": "starting", "heartbeat_at": None,
            "task_status": None, "failure_kind": None, "api_status": None,
            "report_available": False,
        }
        write_json(run_dir / "metadata.json", metadata)
        proc = None
        code = 2
        old_handlers = {}

        def interrupt(signum, frame):
            raise Interrupted(signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, interrupt)
        try:
            with prompt.open("rb") as stdin, (run_dir / "stdout.json").open("wb") as stdout, \
                    (run_dir / "stderr.log").open("wb") as stderr:
                proc = subprocess.Popen(cmd, cwd=workspace, stdin=stdin, stdout=stdout,
                                        stderr=stderr, start_new_session=True,
                                        pass_fds=(lock.fileno(),))
                metadata["claude_pid"] = proc.pid
                write_json(run_dir / "metadata.json", metadata)
                wait_for_cli(proc, metadata, run_dir, args.timeout_seconds)
            # Even a nonzero CLI exit can carry useful structured API evidence.
            if proc.returncode != 0:
                metadata["failure_kind"] = "signal" if proc.returncode < 0 else "cli_exit"
            result = read_result(run_dir / "stdout.json", session_id)
            metadata.update(failure_details(result, proc.returncode))
            if proc.returncode != 0:
                raise ValueError("Claude exited nonzero; inspect stderr.log and stdout.json")
            report = read_report(result)
            denied = bool(result.get("permission_denials"))
            needs_permission = denied or bool(report["permission_requests"])
            if needs_permission:
                # Requests are evidence for Astra, never executable approval rules.
                request_path = run_dir / "permission-request.json"
                write_json(request_path, {
                    "session_id": session_id, "workspace": str(workspace),
                    "requests": report["permission_requests"],
                    "cli_denials": result.get("permission_denials") or [],
                })
                metadata["permission_request_path"] = str(request_path)
                if report["status"] != "failed":
                    report["status"] = "needs_permission"
                report["limitations"].append(
                    "Astra decision required; inspect permission-request.json before resuming.")
            write_json(run_dir / "report.json", report)
            lines = ["# " + report["status"], "", report["summary"]]
            for key in ("changed_files", "verification", "limitations"):
                lines += ["", "## " + key.replace("_", " "), ""]
                lines += ["- " + value for value in report[key]] or ["- None reported."]
            if needs_permission:
                lines += ["", "## Permission requests", "",
                          "See permission-request.json for exact commands and CLI denials.",
                          "Requests have not been approved or executed by the runner."]
            (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            metadata.update(status=report["status"],
                            task_status=report["status"], report_available=True,
                            failure_kind="task_failed" if report["status"] == "failed" else None,
                            session_confirmed=True, permission_denials=denied,
                            model_usage=result.get("modelUsage"),
                            estimated_cost_usd=result.get("total_cost_usd"))
            code = {"ready_for_review": 0, "needs_permission": 4,
                    "blocked": 3, "failed": 2}[metadata["status"]]
        except subprocess.TimeoutExpired:
            metadata["status"] = "timeout"
            metadata["failure_kind"] = "timeout"
            code = 124
        except Interrupted as exc:
            metadata["status"] = "interrupted"
            metadata["failure_kind"] = "interrupted"
            code = 128 + exc.signum
        except (OSError, ValueError) as exc:
            metadata.update(status="error", error=str(exc))
            if metadata["failure_kind"] is None:
                metadata["failure_kind"] = (
                    "spawn_error" if proc is None else
                    "io_error" if isinstance(exc, OSError) else "protocol_error")
        finally:
            # Ignore repeated interrupts while reaping the process group.
            for sig in old_handlers:
                signal.signal(sig, signal.SIG_IGN)
            if proc is not None:
                try:
                    if code in (124, 130, 143) or proc.poll() is None:
                        terminate_group(proc)
                    metadata["claude_exit_code"] = proc.wait()
                except OSError as exc:
                    metadata.update(status="cleanup_error", error=str(exc),
                                    failure_kind="cleanup_error",
                                    claude_exit_code=proc.poll())
                    code = 2
            metadata.update(finished_at=time.time(), runner_exit_code=code)
            metadata["process_state"] = "unknown" if metadata["status"] == "cleanup_error" else "exited"
            write_json(run_dir / "metadata.json", metadata)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
        output = {"status": metadata["status"], "session_id": session_id,
                  "run_dir": str(run_dir), "exit_code": code}
        for key in ("process_state", "task_status", "failure_kind", "api_status",
                    "claude_exit_code", "report_available", "finished_at"):
            output[key] = metadata[key]
        if "permission_request_path" in metadata:
            output["permission_request_path"] = metadata["permission_request_path"]
        print(json.dumps(output), flush=True)
        return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("run_phase: " + str(exc), file=sys.stderr)
        sys.exit(2)
