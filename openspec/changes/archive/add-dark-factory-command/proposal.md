# Change: Add /dark-factory command

**Status: COMPLETED — Superseded by `dark-factory-sdk-migration`**

## Why
The existing vibe-coding pipeline (/ideate -> /spec-create -> /spec-to-issues -> /implement)
requires human orchestration at every handoff. Engineers must manually invoke each command
and bridge context between them. This friction prevents the "dark factory" vision: a single
command that turns the crank from Jira ticket to tested PR with humans only at decision points.

## What Changes
- New slash command: `/dark-factory <jira-key> [--dry-run]`
- First command to use Task tool sub-agents for parallel/isolated work
- First command to use OpenSpec validation as an inline quality gate
- Integrates Atlassian MCP (Jira), beads CLI, OpenSpec, and GitHub CLI

## Impact
- New file: `commands/dark-factory.md`
- Modified file: `CLAUDE.md` (add to slash commands table)
- New dependency: openspec CLI must be available

## Resolution
This change was the original vision for a markdown slash command using Claude Code's
built-in Task tool sub-agents. The approach was superseded by `dark-factory-sdk-migration`,
which implements the same pipeline as a Python orchestrator package using `claude-code-sdk`
direct calls. The SDK approach provides typed responses, per-agent tool guards via
`can_use_tool`, cost tracking, and deterministic phase ownership — capabilities not
achievable through the Task tool approach.

All requirements in `specs/dark-factory/spec.md` are fulfilled by the SDK implementation.
Archived 2026-03-21.
