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
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready_for_review", "blocked", "failed"]},
        "summary": {"type": "string"},
        **{key: {"type": "array", "items": {"type": "string"}}
           for key in ("changed_files", "verification", "limitations")},
    },
    "required": ["status", "summary", "changed_files", "verification", "limitations"],
    "additionalProperties": False,
}
INSTRUCTIONS = """You implement one phase for Astra, who owns planning and acceptance.
Follow the brief and applicable project guidance. You are not alone in the workspace:
preserve pre-existing edits and do not edit coordinator-owned planning/run artifacts.
Own in-scope discovery, implementation, testing and debugging. Do not spawn agents,
invoke another coding CLI, or delegate through skills, shell commands or MCP.
Do not commit, stage, push, deploy, change providers or expand permissions.
If blocked, stop and report the concrete blocker. Do not claim acceptance.
If the brief requests a full task-report, write it to its assigned task-owned path
outside runner artifacts. Leave any Astra-only review record for Astra.
Return the requested structured report: status ready_for_review, blocked or failed,
summary, changed_files, verification (commands, outcomes and evidence paths),
limitations. Include checks you could not run. Empty evidence is not passing tests.
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


def read_report(path, session_id):
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("type") != "result":
        raise ValueError("expected a Claude result object")
    if result.get("session_id") != session_id:
        raise ValueError("result session ID does not match requested session")
    if result.get("is_error") is not False or result.get("subtype") != "success":
        raise ValueError("Claude reported a non-success result; inspect stdout.json")
    report = result.get("structured_output")
    if not isinstance(report, dict) or set(report) != set(SCHEMA["required"]):
        raise ValueError("missing or invalid structured report fields")
    if report["status"] not in ("ready_for_review", "blocked", "failed"):
        raise ValueError("invalid report status")
    if not isinstance(report["summary"], str) or not report["summary"].strip():
        raise ValueError("report summary must be nonempty text")
    for key in ("changed_files", "verification", "limitations"):
        if not isinstance(report[key], list) or not all(isinstance(v, str) for v in report[key]):
            raise ValueError("invalid report list: " + key)
    return result, report


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
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
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
    if args.effort:
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
        prompt.write_text(INSTRUCTIONS + "\n## Phase brief\n\n" + brief, encoding="utf-8")
        metadata = {
            "workspace": str(workspace), "model": args.model, "session_id": session_id,
            "resume_from": str(args.resume_from.resolve()) if args.resume_from else None,
            "started_at": time.time(), "status": "running", "command": cmd,
            "runner_pid": os.getpid(), "claude_exit_code": None,
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
                proc.wait(timeout=args.timeout_seconds)
            if proc.returncode != 0:
                raise ValueError("Claude exited nonzero; inspect stderr.log and stdout.json")
            result, report = read_report(run_dir / "stdout.json", session_id)
            denied = bool(result.get("permission_denials"))
            if denied:
                report["status"] = "blocked"
                report["limitations"].append(
                    "Claude reported permission denials; inspect stdout.json before resuming.")
            write_json(run_dir / "report.json", report)
            lines = ["# " + report["status"], "", report["summary"]]
            for key in ("changed_files", "verification", "limitations"):
                lines += ["", "## " + key.replace("_", " "), ""]
                lines += ["- " + value for value in report[key]] or ["- None reported."]
            (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            metadata.update(status="blocked" if denied else report["status"],
                            session_confirmed=True, permission_denials=denied,
                            model_usage=result.get("modelUsage"),
                            estimated_cost_usd=result.get("total_cost_usd"))
            code = {"ready_for_review": 0, "blocked": 3, "failed": 2}[metadata["status"]]
        except subprocess.TimeoutExpired:
            metadata["status"] = "timeout"
            code = 124
        except Interrupted as exc:
            metadata["status"] = "interrupted"
            code = 128 + exc.signum
        except (OSError, ValueError) as exc:
            metadata.update(status="error", error=str(exc))
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
                                    claude_exit_code=proc.poll())
                    code = 2
            metadata.update(finished_at=time.time(), runner_exit_code=code)
            write_json(run_dir / "metadata.json", metadata)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
        print(json.dumps({"status": metadata["status"], "session_id": session_id,
                          "run_dir": str(run_dir), "exit_code": code}))
        return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("run_phase: " + str(exc), file=sys.stderr)
        sys.exit(2)
