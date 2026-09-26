# Direct Claude Code runner

Requirements: Python 3.9+, macOS/Linux (`fcntl`), and an authenticated Claude Code
CLI supporting `-p`, `--json-schema`, `--session-id`, `--resume` and
`--permission-prompts none` (the last flag requires v2.1.259+). Locally inspected
CLI: 2.1.283. No Python dependencies, server, relay or native Codex role is needed.
This does not change how the primary Astra session reaches its own provider.

Run from any directory; replace example paths with actual absolute paths:

```sh
python3 /path/to/astra-claude-orchestrator/scripts/run_phase.py \
  --workspace /path/to/project \
  --brief /path/to/project/docs/agent-work/feature/phase-1.md \
  --run-dir /path/to/project/docs/agent-work/feature/runs/phase-1 \
  --model claude-opus-5-5 \
  --allow-tool 'Bash(npm test *)'
```

`--model` defaults to `claude-opus-5-5` (Opus 5.5), selected by the user.
Override only on request. Optional `--effort` must
match the installed CLI/model. The wrapper never sets a fallback model.
Repeat `--allow-tool` for additional authorized commands. Default allow rules are
Read, Glob, Grep, Edit and Write; `--read-only` removes Edit/Write and explicitly
denies those tools. Read-only mode is a tool policy, not OS isolation; additional
Bash rules, project hooks and existing settings must be considered separately.
Existing Claude settings, hooks, credentials and project instructions still apply.
No shell is used to interpolate the brief or arguments. The complete prompt goes
over stdin. Do not put secrets in prompts, tool rules or model arguments.

Correction or recovery:

```sh
python3 /path/to/astra-claude-orchestrator/scripts/run_phase.py \
  --workspace /path/to/project \
  --brief /path/to/project/docs/agent-work/feature/corrections.md \
  --run-dir /path/to/project/docs/agent-work/feature/runs/phase-1-fix \
  --resume-from /path/to/project/docs/agent-work/feature/runs/phase-1 \
  --model claude-opus-5-5 \
  --allow-tool 'Bash(npm test *)'
```

Resume requires the same canonical workspace and requested model. The original
run's metadata records the generated session ID before launch, even if no final
JSON arrives. After an early failure that ID might not exist in Claude's store;
resume may fail and must not silently start a new session. Permissions and other
options are supplied again deliberately; previous allow rules are not copied.

Every run directory is new, private by default, and contains:

- `prompt.md`: exact brief plus worker instructions sent on stdin.
- `metadata.json`: workspace, requested model, session ID, process/runner exit
  codes, times, status, resume source and command arguments (no environment dump).
- `stdout.json` and `stderr.log`: original CLI output, including failure evidence.
- `report.json` and `report.md`: validated structured report, when available.

The runner's compact transport report supplements `templates/task-report.md`.
The phase brief must give the worker the full task-report template and a unique
task-owned output path outside the runner's artifact directory. The worker writes
that complete report, including baseline, command exits and resume checkpoint;
only Astra fills its Astra-only review record. In the final structured response,
link to that report and its evidence. Do not replace the original report/checkpoint
contract with the runner's shorter JSON schema. A worker status of `failed` is
preserved in both transport reports and exits 2; only Astra may accept any result.

Logs and prompts may contain private project content. Keep artifacts local and
out of commits unless reviewed. The runner does not recursively snapshot files,
modify Git ignore rules, stage files, or clean up a failed worker's edits.

The `.astra-claude.lock` advisory lock lives at the Git toplevel when available,
otherwise at the workspace. It remains as a harmless file after completion;
never delete it to unlock a live run. The child inherits the open lock descriptor
so a killed wrapper does not immediately permit another writer while it lives.
This lock only coordinates this runner on this machine, not arbitrary processes.

Exit codes: 0 = ready for Astra review; 2 = failed task or invocation/CLI/protocol error;
3 = reported blocked or permission denials; 124 = configured timeout;
130/143 = SIGINT/SIGTERM. Raw Claude exit code is recorded separately.
The wrapper sends SIGTERM to the process group on timeout/interruption, gives
the group five seconds to clean up (even if the direct child exits first), then
sends SIGKILL to remaining members. A cleanup permission failure is recorded as `cleanup_error` (exit 2);
inspect the recorded PID before resuming. An OS kill/power loss can leave `status: running` in
metadata; inspect process state and the workspace before recovery.

No deadline is imposed by default. `--timeout-seconds N` sets one explicitly.
`--max-budget-usd N` passes Claude's API budget option; this is not a guaranteed
subscription/billing cap. Cost estimates on resumed conversations can include
earlier turns: never sum them as independent charges.

Source documentation checked 2026-09-27:
- https://code.claude.com/docs/en/headless (JSON, resume, permissions, metadata)
- https://code.claude.com/docs/en/cli-reference (CLI options)
- https://platform.claude.com/docs/en/about-claude/models/overview (Opus 5.5 ID)

Run offline regression checks from the skill directory:
`python3 -m unittest discover -s tests -v`.
