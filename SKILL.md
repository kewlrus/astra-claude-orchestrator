---
name: astra-claude-orchestrator
description: Use only when the user explicitly requests $astra-claude-orchestrator or names this skill for use. Plan and execute substantial multi-file builds, features, migrations, and refactors with Astra as orchestrator and Claude Code Opus 5.5 as the local CLI implementation worker, including existing Superpowers or GSD plans. Do not activate based on task complexity alone. Skip trivial edits and explicitly single-agent tasks. Workers must not invoke this orchestration skill.
---

# Astra plans. Claude Code implements. Astra accepts.

Этот skill задаёт рабочий процесс, а не переключает модель текстом промпта.
Модель исполнителя закреплена в локальном runner; исполнитель — установленный Claude Code.
Используй прямой вызов `claude -p` через `scripts/run_phase.py` с сохранением
отчёта и session ID. Не используй relay, сервер или собственный API-runner.

| Назначение | Значение |
|---|---|
| Основная сессия | выбранная пользователем Astra; ожидаемый alias `gpt-6-astra` |
| Исполнитель | локальный процесс Claude Code через `scripts/run_phase.py` |
| Модель исполнителя | Opus 5.5, `claude-opus-5-5` |
| Effort исполнителя | обязательно явный `--effort medium`; другое значение только по указанию пользователя |
| Провайдер и авторизация | существующая разрешённая конфигурация Claude Code |
| Параллелизм | один пишущий исполнитель по умолчанию |

Не меняй root model, её effort, global subagent defaults, URL, заголовки,
credentials, sandbox или глобальные permissions ради выполнения задачи.
Astra может добавить узкое разрешение `--allow-tool` для конкретного продолжения
после проверки запроса исполнителя по `references/permissions.md`; это не bypass
и не расширение пользовательского поручения. Используй точный
ID `claude-opus-5-5`, без плавающего alias `opus` и автоматического fallback.
Не подменяй модель молча ни на Astra, ни на другого исполнителя.
Для Opus 5.5 при каждом запуске, включая resume и повтор после сбоя, обязательно
передавай `--effort medium`, если пользователь не задал иное. Не полагайся на
настройки Claude Code и не наследуй effort Astra. Указанный пользователем override
передавай явно и сохраняй при продолжении той же задачи, пока пользователь его не изменит.

## Supported orchestration workflow

There is no user-selectable mode switch. Thin-root orchestration is the only
supported delegated workflow. “Thin” distinguishes this design from older,
more Astra-active revisions; it is not one option in a mode menu.

Keep Astra focused on decisions where its judgment has the highest leverage:
architecture, acceptance criteria, material risk, and final acceptance. After the
contract is ready, Claude Code owns repository discovery needed within the brief,
implementation, testing, debugging, and routine browser/visual QA.

For a normal phase, target this root workflow: one planning batch, one dispatch to
one worker, one process wait, one batched acceptance review, and one final response.
This is a workflow shape, not a reason to skip evidence or stop before the result is
correct. Add Astra work only for a concrete blocker or architecture, security, or
production-risk concern. Do not create root activity merely to observe progress.

Token economy must preserve every required stage, artifact and acceptance check.
Reuse reference text already read in the current context; reread it when changed
or no longer available. Avoid printing identical report representations and full
CLI help repeatedly. This does not narrow source review or required evidence.

## 1. Orient and classify

Read the relevant repository guidance and current request. Preserve existing
work. Decide whether this is a direct small fix, a bounded build, or a large
multi-phase project. Keep trivial edits with Astra; do not force delegation onto
a typo or a simple question. For a substantial build, say what Astra will own
and what Claude Code will implement. These routing decisions are not alternate modes.

Use the user's existing approvals and decisions. An explicit request to plan and
build authorizes the in-scope workflow; it is not necessary to ask again after
every phase. Ask only about material unresolved product/risk decisions that
cannot be established from the repo. When asked to plan only, do not implement.

## 2. Confirm routing before delegating

Перед первой задачей прочитай `references/routing.md`. Проверь по доступным
настройкам наличие Claude Code CLI, ожидаемого model ID и разрешённого провайдера.
Проверь применимые инструкции проекта, запреты передачи кода третьим сторонам,
разрешения на изменения и уже принятые пользователем решения.
Не читай auth-файлы и не печатай значения секретов ради проверки настроек.

Наличие CLI или model ID в настройках — только статическая проверка. Реальный
маршрут подтверждается метаданными CLI-сессии и провайдера, не словами
самого агента. Для новой конфигурации используй минимальную полезную задачу
на разрешённых данных; не запускай отдельную платную проверку автоматически.
Если Claude Code или прямой запуск недоступны, останови исполнение,
сохрани план и назови конкретный блокер. Не переходи на relay или другого исполнителя.

## 3. Design before dividing the work

Read `references/planning.md`. Reuse an approved design/spec and phase plan when
one exists. Superpowers, GSD, and custom plans are all valid inputs; do not create
a competing spec or force a framework migration.

For new work, produce an appropriately sized design covering objective,
non-goals, repo evidence, important alternatives, interfaces, failure behavior,
risks, and acceptance criteria. Put stable shared contracts ahead of dependent
implementation. Astra makes architecture, auth/security, tenancy, payments,
secrets, and production-impacting decisions; do not hand those decisions to
Claude Code under a vague "build it" prompt.

## 4. Produce a phase plan and executable briefs

Default artifact home: `docs/agent-work/<feature>/`. Follow an existing project
convention instead when one is established. Use the templates as needed.

Write a dependency-ordered phase plan. Prefer one coherent end-to-end vertical
bundle per phase when its contract is stable. Each Claude Code assignment has exact
contracts, a bounded file scope, testable outcomes, and verification commands.
Internal discovery, implementation, testing, debugging, and routine UI validation
stay with Claude Code; Astra does not write the entire implementation in the plan. Long
work is welcome inside a clear contract, not across unknown architecture boundaries.

Separate tasks only at genuine dependency or independent acceptance boundaries,
not for status visibility, every function, or every five-minute step. A phase can
contain multiple bundles when required; a bundle can contain multiple test/code/fix
cycles. Complete early phases first and refine later briefs when earlier interfaces
stabilize. If a machine-readable plan is useful, use
`templates/plan.json` and run
`scripts/validate_plan.py <plan.json> --repo-root <repository-root>` before launch.
That linter checks structure, not the truth or quality of the design.

## 5. Dispatch and let the worker work

Read `references/execution.md`.

Используй `scripts/run_phase.py`, который запускает установленный `claude -p`.
Передай workspace, полный brief и новый run directory; модель по умолчанию —
`claude-opus-5-5`. Прочитай `references/runner.md` для аргументов и артефактов.
Не выдумывай сигнатуру инструмента, slash-команду или несуществующий аргумент.
Не меняй model/effort молча и не запускай нативный Codex child вместо Claude Code.

В sandbox-host заранее учитывай доступ Claude к существующей авторизации,
сети и хранилищу сессий. Если для этого окружения уже выявлено ограничение,
запрашивай штатное разрешение host на запуск runner вне sandbox, не повторяя
заведомо нерабочий запуск. Это разрешение на конкретный процесс, а не изменение
глобальных sandbox/permissions или bypass в Claude. При `Not logged in` до
API-вызова и несохранённой сессии следуй разделу «Sandbox host и ранняя ошибка
авторизации» в `references/runner.md`: ID в metadata ещё не означает, что resume
возможен. Не запускай второго writer, пока первый процесс не завершён.

Give the worker the full task brief plus the minimum shared context, required
contracts, task ID, working directory, baseline, and relevant dependency outputs.
Use a new Claude session for a new bundle; never claim its context is empty:
Claude Code loads its own project guidance and configuration. No unnecessary full-transcript
forking, duplicate repository investigation, or play-by-play log forwarding.

Default to ONE active Claude Code writer in the current workspace. A CLI process
is not automatically a Git worktree or a security sandbox. Astra must not edit
its claimed paths. Use two writers only when the plan explicitly identifies
independent work and each has a real, verified separate workspace. See execution
reference for dirty-tree, contract, and integration rules. No recursive agents.

Let the worker complete its internal implementation, testing, debugging, and
routine UI-validation loop. Announce dispatch once, then use the host's completion
notification or longest permitted process wait. Wait silently: do not send repeated
"still running / awaiting results" messages without new information. The runner
monitors its child locally; do not return control to Astra on a periodic heartbeat.
Do not poll progress with status/list calls, request updates, interrupt a healthy
run, or perform overlapping repository work while the worker owns the bundle.
Higher-priority host wait/communication requirements still apply; this skill does
not change them or promise notifications the host cannot deliver.

After a lost/interrupted wait or context recovery, use `scripts/check_run.py`
once for the exact run/session before waiting again. This lifecycle recovery is
not progress polling; do not turn it into a scheduled model loop. Terminal metadata
ends report waiting even when no worker report exists. A stale heartbeat means
unknown, not a dead child or permission for a second writer. See
`references/runner.md` for failure handling and the read-only check command.
A wait timeout alone is not evidence that the worker is stuck. Set a
task-appropriate budget and checkpoint rule rather than assuming every job fits a
fixed time estimate. Resume the same worker for one consolidated review-fix cycle;
start a fresh context for an unrelated bundle, or for the documented early-start
recovery when no resumable session exists. Use `--resume-from` with the
previous run directory and a new output directory; never select an unrelated
conversation through `--continue`. A host wait timeout is not a runner deadline.

## 6. Review the actual result

Сначала обработай terminal outcome runner. При API/CLI/protocol error, timeout
или interruption сообщи причину и пути к evidence; сохрани частичные изменения,
не ожидай обязательного отчёта от аварийно завершившегося агента и не объявляй
его работу принятой. HTTP 429 не запускает автоматический resume/fallback.
При `cleanup_error`/unknown не запускай нового writer до проверки процессов.
Только `ready_for_review` передаёт результат в обычную приёмку ниже.

Если runner вернул `needs_permission` (exit 4), сначала прочитай
`permission-request.json` и `references/permissions.md`. Исполнитель передаёт
Astra точную команду, cwd, цель и ожидаемые эффекты. Astra принимает решение в
пределах уже разрешённой задачи, сохраняет его в brief и продолжает ту же сессию
через `--resume-from` с явно выбранными allow rules. Это отдельный обмен по
разрешениям, не цикл исправлений по ревью. Не считай запрос провалом реализации,
не одобряй команды автоматически и не перекладывай обычные решения на пользователя.

Read `references/review.md`. Worker completion means **ready for review**, not
accepted. Astra reviews the actual patch against the captured baseline, including
untracked additions and pre-existing changes. Never treat HEAD as the baseline
without checking the workspace state.

Apply two review lenses in one batched Astra pass: specification compliance, then
code quality/security. Inspect the actual diff and the worker's evidence. Perform
targeted spot checks where evidence is missing, a failure is plausible, or the risk
justifies independent confirmation. Do not routinely rerun the worker's complete
test suite or repeat visual QA that has adequate artifacts. The runner pins
Opus 5.5 without changing global subagent defaults; do not mistake a Claude Code
session for an independent Astra review without checking its actual model.

Accept only after both lenses and relevant verification succeed. If corrections
are needed, return all precise file-level findings to the same worker in one request.
Default to at most one correction cycle, then accept or explicitly reassess the
scope and risk. A second cycle is reserved for a material unresolved issue in the
high-assurance exception below. Never silently switch model/provider.

## 7. Integrate, checkpoint, and finish

Astra integrates accepted dependencies in order, with the user's existing Git
permissions. Do not auto-commit, merge branches, push, deploy, or apply production
migrations just because a phase finished. Shared-workspace edits already exist in
the workspace; don't invent a branch merge. Separate-worktree integration needs
an explicit, reviewed operation and a valid common baseline.

Run cross-task checks once at a genuine integration boundary, and only when those
checks add coverage beyond the worker's accepted evidence. Update the plan and a
compact `CHECKPOINT.md` at meaningful resumable boundaries, not after every turn:
completed/accepted work, current diff/workspace, contract decisions, pending tasks,
worker session IDs and run directories, review status, exact resume action. Preserve evidence before
context compaction. Do not repeatedly reload full logs.

Conclude with what was built, what actually passed, outstanding limits, and the
observed routing state (`static_only`, `inference_verified`, or `unverified`). Never estimate cost savings from task counts
or durations. Use actual provider usage records when measuring costs.

## High-assurance exception

Expand Astra's investigation, checks, or correction cycle only when evidence shows
material risk involving architecture, authentication/authorization, payments,
tenancy, secrets, destructive migrations, production behavior, or high-impact
shared infrastructure. State the reason for expanding the root loop. High assurance
does not justify progress polling, duplicate implementation, or ritual reruns.
