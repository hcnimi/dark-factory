## Why

The `/dark-factory` pipeline (760-line markdown slash command) burns ~50-60% of its tokens on deterministic work the LLM doesn't need to do — arg parsing, git operations, CLI calls, template rendering, progress tracking. Each run rediscovers the same repo patterns, has no observability into phase timing or cost, and relies on prompt instructions for safety enforcement instead of code-level guards. Field data from 8 runs on Backstage (75% clean PR rate) validates the pipeline works, but also exposed three failure modes that prompt-based orchestration can't fix: CI environment blindness (SDLC-3019), silent pipeline death with no event trail (SDLC-2888), and zero cross-run learning.

## What Changes

- **BREAKING**: `/dark-factory` command migrates from a self-contained markdown slash command to a thin launcher that delegates to `dark_factory.py` — a Python orchestrator using the `claude-code-sdk`
- Phases 0, 5, 6, 10 (100% deterministic) move to Python functions — zero LLM tokens
- Phase 1 (source ingestion) becomes deterministic Jira/file parsing with LLM only for inline interview
- Phase 2 splits into deterministic pre-fetch (2a) + focused agent exploration (2b) — fixes CI blindness
- Phases 7, 8, 9 become `claude-code-sdk` calls with `max_turns`, `allowed_tools`, and `can_use_tool` security callbacks
- Phase 11 (PR creation) becomes deterministic push/create with a single focused LLM call for PR body
- JSON state management replaces markdown progress file
- Per-phase timing and cost tracking via `ResultMessage` fields
- Security policy enforcement via `can_use_tool` callback (replaces prompt-based "do NOT" instructions)
- Model tiering: sonnet for review/exploration, opus for implementation/spec generation

## Capabilities

### New Capabilities

- `deterministic-orchestration`: Python state machine that owns all phase transitions, progress tracking, and deterministic operations (arg parsing, git ops, CLI calls, template rendering) — the LLM never decides "what phase am I in"
- `context-prefetch`: Deterministic pre-fetch of repo structure, CI config, test infrastructure, and convention files before the LLM wakes up — addresses CI blindness and eliminates redundant exploration
- `sdk-agent-calls`: Focused `claude-code-sdk` invocations with per-agent `model`, `max_turns`, `allowed_tools`, and `can_use_tool` security policy — replaces unbounded prompt-based sub-agents
- `pipeline-observability`: Per-phase timing, cost tracking, and event logging via `ResultMessage` — enables diagnosis of silent failures and cost optimization

### Modified Capabilities

_(none — no existing specs)_

## Impact

- **Code**: `commands/dark-factory.md` (760 lines) → thin launcher (~50 lines) + `dark_factory.py` (~300 lines)
- **Dependencies**: New dependency on `claude-code-sdk` (Python, v0.0.25+)
- **Runtime**: Python 3.10+ required in execution environment
- **Cost**: ~50-60% token savings per run (7-9 focused LLM calls vs current full-context interpretation of 760 lines)
- **Observability**: New `.dark-factory/<KEY>.json` state files with timing/cost data
- **Security**: Deterministic `can_use_tool` enforcement replaces prompt-based safety instructions
- **Compatibility**: Existing `/dark-factory` CLI interface (`<jira-key>`, `<file-path>`, `"<description>"`, `--dry-run`, `--resume`) preserved
