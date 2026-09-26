# Sources and provenance

Original workflow documentation checked September 20, 2026. The source package
instructions and utilities are not a copy or distribution of Superpowers.
Upstream documentation and local client behavior may change independently.

## Claude Code routing adaptation

The workflow, templates and plan validator are ported from the local
`astra-flash-orchestrator` package, retaining its planning, execution and acceptance
rules. Only executor identity and routing are adapted. The original remains unchanged.
The active route is local `claude -p` through `scripts/run_phase.py`, using
Opus 5.5 (`claude-opus-5-5`), saved reports and resumable Claude session IDs.
No relay, server or native Codex worker role is required.

Routing documentation checked September 27, 2026; local CLI 2.1.283.
- [Claude Code headless](https://code.claude.com/docs/en/headless): non-interactive
  execution, structured reports, session continuation and permission handling.
- [Claude Code CLI](https://code.claude.com/docs/en/cli-reference): command flags.
- [Claude model overview](https://platform.claude.com/docs/en/about-claude/models/overview):
  Opus 5.5 model ID.

## Official Codex documentation

- [Build skills](https://learn.chatgpt.com/docs/build-skills): local skill layout,
  user discovery under ~/.agents/skills, explicit/implicit invocation, metadata.
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents): child
  model defaults, custom agent configuration and model precedence, native roles.
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference):
  model_catalog_json, user configuration and profile considerations.
- [Codex customization](https://developers.openai.com/codex/customization/overview):
  distinction between durable AGENTS guidance, skills, external tools and agents.

## Primary project/vendor documentation

- [Superpowers brainstorming](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md):
  discovery/design before implementation.
- [Superpowers writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md):
  explicit file/contracts/tests and independently reviewable deliverables.
- [Superpowers subagent-driven-development](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md):
  bounded implementer context, task review and broad final review.

## Provenance

The package contains original workflow instructions and Python utilities. Its design was informed by a private prototype review and the public references above. Private attachments, prototype runner code, local configuration and personal review notes are not distributed. Upstream projects are referenced, not bundled or relicensed.
