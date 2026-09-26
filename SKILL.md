---
name: astra-claude-orchestrator
description: Plan and execute substantial multi-file builds, features, migrations, and refactors with Astra as orchestrator and Claude Code Opus 5.5 as the local CLI implementation worker. Use for phased planning and delegated build execution, including existing Superpowers or GSD plans. Skip trivial edits and explicitly single-agent tasks. Workers must not invoke this orchestration skill.
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
| Effort исполнителя | настройки Claude Code; явный override только по решению пользователя |
| Провайдер и авторизация | существующая разрешённая конфигурация Claude Code |
| Параллелизм | один пишущий исполнитель по умолчанию |

Не меняй root model, её effort, global subagent defaults, URL, заголовки,
credentials, sandbox или permissions ради выполнения задачи. Используй точный
ID `claude-opus-5-5`, без плавающего alias `opus` и автоматического fallback.
Не подменяй модель молча ни на Astra, ни на другого исполнителя.

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
routine UI-validation loop. Use the longest practical process wait and allow it to
finish. Do not poll with status/list calls, request progress updates, interrupt a
healthy run, or perform overlapping repository work while the worker owns the
bundle. A wait timeout alone is not evidence that the worker is stuck. Set a
task-appropriate budget and checkpoint rule rather than assuming every job fits a
fixed time estimate. Resume the same worker for one consolidated review-fix cycle;
start a fresh context only for an unrelated bundle. Use `--resume-from` with the
previous run directory and a new output directory; never select an unrelated
conversation through `--continue`. A host wait timeout is not a runner deadline.

## 6. Review the actual result

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
