#!/usr/bin/env python3
"""Read one run's lifecycle after a lost/interrupted wait; never poll or mutate."""

import argparse
import json
import math
from pathlib import Path
import time
import uuid


MAX_METADATA_BYTES = 256 * 1024
STALE_AFTER_SECONDS = 20.0
TERMINAL_CODES = {
    "ready_for_review": {0}, "needs_permission": {4}, "blocked": {3},
    "failed": {2}, "error": {2}, "cleanup_error": {2}, "timeout": {124},
    "interrupted": {130, 143},
}
FAILURE_KINDS = {
    "api_rate_limit", "api_auth", "api_error", "budget_limit", "turn_limit",
    "cli_exit", "cli_error", "signal", "protocol_error", "spawn_error",
    "io_error", "task_failed", "timeout", "interrupted", "cleanup_error",
}


def timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def check_run(run_dir, expected_session=None, *, now=None):
    result = {"run_dir": str(run_dir), "process_state": "unknown",
              "terminal": False, "reason": "metadata_unavailable"}
    try:
        with (run_dir / "metadata.json").open("rb") as stream:
            data = stream.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise ValueError("metadata exceeds cap")
        meta = json.loads(data)
        if not isinstance(meta, dict):
            raise ValueError("metadata must be an object")
        session = str(uuid.UUID(meta["session_id"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result
    result["session_id"] = session
    if expected_session is not None and session != expected_session:
        result["reason"] = "session_mismatch"
        return result
    status = meta.get("status")
    if not isinstance(status, str) or status not in {"running", *TERMINAL_CODES}:
        result["reason"] = "invalid_status"
        return result
    result["status"] = status
    code = meta.get("runner_exit_code")
    finished = meta.get("finished_at")
    if timestamp(finished) and type(code) is int and code in TERMINAL_CODES.get(status, set()):
        result.update(terminal=True, finished_at=finished, runner_exit_code=code,
                      process_state="unknown" if status == "cleanup_error" else "exited",
                      reason="cleanup_unconfirmed" if status == "cleanup_error" else "terminal_metadata")
        child_code = meta.get("claude_exit_code")
        result["claude_exit_code"] = child_code if type(child_code) is int else None
        task_status = meta.get("task_status")
        result["task_status"] = task_status if isinstance(task_status, str) and task_status in {
            "ready_for_review", "needs_permission", "blocked", "failed"} else None
        result["report_available"] = meta.get("report_available") is True
        kind = meta.get("failure_kind")
        result["failure_kind"] = kind if isinstance(kind, str) and kind in FAILURE_KINDS else None
        api_status = meta.get("api_status")
        result["api_status"] = api_status if type(api_status) is int and 100 <= api_status <= 599 else None
        return result
    if status != "running" or finished is not None or code is not None:
        result["reason"] = "inconsistent_metadata"
        return result
    heartbeat = meta.get("heartbeat_at")
    now = time.time() if now is None else now
    if not timestamp(heartbeat) or meta.get("process_state") != "running":
        result["reason"] = "no_heartbeat"
        return result
    age = now - heartbeat
    result["heartbeat_at"] = heartbeat
    if 0 <= age <= STALE_AFTER_SECONDS:
        result.update(process_state="running", reason="recent_heartbeat")
    else:
        result["reason"] = "stale_heartbeat"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--session-id", type=uuid.UUID)
    args = parser.parse_args()
    expected = str(args.session_id) if args.session_id is not None else None
    print(json.dumps(check_run(args.run_dir.resolve(), expected)), flush=True)


if __name__ == "__main__":
    main()
