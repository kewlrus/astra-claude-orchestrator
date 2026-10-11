# Direct Claude Code runner

Requirements: Python 3.9+, macOS/Linux (`fcntl`), and an authenticated Claude Code
CLI supporting `-p`, `--json-schema`, `--session-id`, `--resume`, `--effort` and
`--permission-prompts none` (the last flag requires v2.1.259+). Locally inspected
CLI: 2.1.283. No Python dependencies, server, relay or native Codex role is needed.
This does not change how the primary Astra session reaches its own provider.

Run from any directory; replace example paths with actual absolute paths:

Set `--workspace` to the implementation repository root (where its Git and
CodeGraph live), not the parent folder containing backlog cards. Quote paths
containing spaces. The runner selects the child's cwd; the host command's
`workdir` should normally point to the same repository for clarity.

```sh
python3 /path/to/astra-claude-orchestrator/scripts/run_phase.py \
  --workspace /path/to/project \
  --brief /path/to/project/docs/agent-work/feature/phase-1.md \
  --run-dir /path/to/project/docs/agent-work/feature/runs/phase-1 \
  --model claude-opus-5-5 \
  --effort medium \
  --allow-tool 'Bash(npm test *)'
```

`--model` defaults to `claude-opus-5-5` (Opus 5.5), selected by the user.
Override only on request. Always specify `--effort medium` for Opus 5.5 unless
the user explicitly requests another supported value. The runner also defaults
to `medium` and always passes `--effort` to Claude, overriding Claude Code settings.
Apply this rule to new sessions, resumes and retries. Repeat any user-requested
effort override explicitly when continuing the same task; the runner does not
inherit effort from previous run metadata. The wrapper never sets a fallback model.
Repeat `--allow-tool` for additional authorized commands. Default allow rules are
Read, Glob, Grep, Edit and Write; `--read-only` removes Edit/Write and explicitly
denies those tools. Read-only mode is a tool policy, not OS isolation; additional
Bash rules, project hooks and existing settings must be considered separately.
Existing Claude settings, hooks, credentials and project instructions still apply.
No shell is used to interpolate the brief or arguments. The complete prompt goes
over stdin. Do not put secrets in prompts, tool rules or model arguments.

Correction or recovery of an existing saved session:

```sh
python3 /path/to/astra-claude-orchestrator/scripts/run_phase.py \
  --workspace /path/to/project \
  --brief /path/to/project/docs/agent-work/feature/corrections.md \
  --run-dir /path/to/project/docs/agent-work/feature/runs/phase-1-fix \
  --resume-from /path/to/project/docs/agent-work/feature/runs/phase-1 \
  --model claude-opus-5-5 \
  --effort medium \
  --allow-tool 'Bash(npm test *)'
```

Resume requires the same canonical workspace and requested model. The original
run's metadata records the generated session ID before launch, even if no final
JSON arrives. After an early failure that ID might not exist in Claude's store;
resume may fail and must not silently start a new session. Permissions and other
options are supplied again deliberately; previous allow rules are not copied.

## Command permission requests to Astra

The structured report includes `permission_requests` (empty when none) and the
status `needs_permission`. On a request or CLI permission denial, the runner
saves `permission-request.json`, prints its path in the transport result and
exits 4. Astra reviews it, records a decision in a new brief, and resumes the
same session with explicitly selected `--allow-tool` rules. Read
`permissions.md` for the request schema, decision scope and complete procedure.
There is no live prompt callback or automatic grant. A worker-reported `failed`
status remains failed/exit 2 even when permission requests also exist.

## Sandbox host и ранняя ошибка авторизации

Следующие правила относятся к запуску из ограниченного shell host, включая
Codex. Они не требуют менять CLI runner, credentials или глобальную конфигурацию.

1. Для уже выявленного ограничения sandbox используй штатный запрос host на
   запуск runner вне sandbox сразу, с тем же workspace, brief, model и узкими
   allow rules. В Codex shell tool это `sandbox_permissions="require_escalated"`
   и `justification` с причиной; это параметры инструмента host, не аргументы
   `run_phase.py`. Соблюдай текущую политику host: если такой запуск запрещён,
   остановись с конкретным блокером. Не добавляй `--dangerously-skip-permissions`,
   не меняй `dontAsk`, HOME, credentials, provider settings или sandbox config.
2. Если сбой уже произошёл, сначала дождись завершения процесса и прочитай
   `metadata.json`, `stderr.log` и безопасные поля `stdout.json`. `Not logged in`
   вместе с `duration_api_ms=0`, нулевым usage и пустым `modelUsage` указывает
   на ранний сбой без наблюдаемого inference; это не доказательство его причины
   или отсутствия сохранённой сессии. Отдельный платный ping не нужен.
3. Runner генерирует session ID ДО запуска Claude. Используй `--resume-from`
   для сохранённой сессии; одно наличие ID в metadata недостаточно. Если
   сохранение неясно, допустима одна адресная попытка resume в разрешённых
   условиях. После `No conversation found with session ID` не повторяй resume
   того же отсутствующего ID и не используй `--continue`.
4. Если ранний сбой не оставил возобновляемой сессии, сообщи об этом и повтори
   исходную задачу БЕЗ `--resume-from`, с новым run directory и новым ID,
   который создаст runner. Сохрани прежние артефакты; перед повтором проверь,
   что старый процесс завершён, и учти возможные изменения рабочего дерева.
   Это явное восстановление запуска той же задачи, а не смена модели или
   автоматический fallback. При существующей сессии продолжай её обычным resume.
5. Если в разрешённых условиях ошибка авторизации остаётся, остановись и
   сообщи конкретный блокер. Не устраивай цикл новых сессий и не исправляй
   авторизацию пользователя самостоятельно. Успех подтверждают результат и
   metadata CLI/provider; сам запуск вне sandbox ничего не доказывает.

Наблюдение 27.09.2026 (Claude Code 2.1.283): sandbox-запуск завершился с
`Not logged in` до API-вызова; последующий resume вернул `No conversation found`.
Это основание для описанного восстановления, но не подтверждение, что причина
точно в Keychain или что любой такой сбой устраняется запуском вне sandbox.

## Артефакты и жизненный цикл

### Завершение без периодического опроса Astra

После сообщения о запуске использовать completion notification или максимально
долгое разрешённое host ожидание процесса. Не создавать модельный цикл ради
сообщений «агент ещё работает». Runner ждёт дочерний процесс сам: каждые 5 секунд
атомарно обновляет `heartbeat_at` в metadata без stdout, вызовов моделей и сети.
Heartbeat означает последнее наблюдение живого процесса, не прогресс или здоровье
задачи. Host ограничения на ожидание/сообщения остаются в силе; skill их не меняет.

На завершении runner атомарно сохраняет metadata и печатает один компактный
результат с flush. Сохраняются прежние status/exit codes и permission protocol;
добавлены `process_state`, `task_status`, `failure_kind`, `api_status`,
`report_available`. Process completion не равно готовности задачи: при аварии
`task_status=null`, `report_available=false`, но ожидание отчёта уже закончено.
JSON CLI разбирается и при ненулевом exit. `is_error=true` не считается успехом,
даже если `subtype=success`. Raw API message остаётся в stdout.json, компактный
результат содержит только классификацию: api_rate_limit, api_auth, api_error,
budget_limit, turn_limit, cli_exit/cli_error, signal, protocol_error, spawn_error,
io_error, timeout, interrupted, cleanup_error или task_failed.

Если ожидание прервано, terminal notification не получен или восстановлен контекст,
однократно выполнить read-only проверку конкретного запуска:

```sh
python3 /path/to/skill/scripts/check_run.py \
  --run-dir /path/to/run \
  --session-id 00000000-0000-0000-0000-000000000000
```

Подставить сохранённый ID именно этого запуска. Helper читает только bounded
metadata, не Claude transcript, не репозиторий; ничего не пишет, не посылает
сигналов, не возобновляет сессию и не опрашивает процессы по PID. Exit 0 означает
выполненную диагностику, а не успешную задачу. Результат:

- `terminal=true`: обработать записанный исход, даже без report.json и без
  финального stdout host-инструмента. `ready_for_review` идёт на обычное ревью;
  needs_permission — по существующему протоколу; ошибка — сообщить причину,
  сохранить частичные правки и ссылки на evidence, не объявлять приёмку.
- `terminal=false, process_state=running`: heartbeat не старше 20 секунд;
  это недавнее наблюдение жизни, не доказательство текущего прогресса. Вернуться
  к host ожиданию без периодических сообщений или новых check-вызовов.
- `process_state=unknown`: metadata отсутствует/повреждена/противоречива,
  session не совпала или heartbeat устарел/отсутствует. Адресно проверить этот
  запуск в пределах разрешений host; не считать PID или старый status=running
  доказательством жизни и не запускать второго writer. `cleanup_error` также
  даёт unknown: runner завершился, но очистка процессов не подтверждена.

Старые terminal metadata читаются без heartbeat; причина API может потребовать
одного чтения stdout.json. 429 во время CLI retries не равен завершению процесса.
После terminal 429 автоматический resume/fallback не выполняется. Missing report
не повод ждать уже завершившийся процесс. Сам helper — резерв восстановления
состояния, не обязательный периодический polling. SIGKILL runner может оставить
живого ребёнка: stale heartbeat не разрешает его убить или начать нового writer.

### Сохраняемые файлы

Every run directory is new, private by default, and contains:

- `prompt.md`: exact brief plus worker instructions sent on stdin.
- `metadata.json`: workspace, requested model, session ID, process/runner exit
  codes, times, status, resume source and command arguments (no environment dump).
- `stdout.json` and `stderr.log`: original CLI output, including failure evidence.
- `report.json` and `report.md`: validated structured report, when available.
- `permission-request.json`: when needed, session/workspace-bound requests and
  raw CLI denials for Astra's decision; commands are not executed by the runner.

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
3 = reported blocked; 4 = needs Astra permission decision; 124 = configured timeout;
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
