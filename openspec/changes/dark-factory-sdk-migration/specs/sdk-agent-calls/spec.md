## ADDED Requirements

### Requirement: LLM calls use claude-code-sdk
All LLM invocations SHALL use the `claude-code-sdk` Python package (`query()` or `ClaudeSDKClient`). The orchestrator SHALL NOT use `claude -p` subprocesses or direct Anthropic API calls.

#### Scenario: SDK query for bounded tasks
- **WHEN** the orchestrator needs a bounded LLM call (exploration, review, PR body)
- **THEN** it uses `query()` with `ClaudeCodeOptions` specifying `model`, `max_turns`, `allowed_tools`, and `cwd`

#### Scenario: SDK client for implementation
- **WHEN** the orchestrator spawns an implementation agent (Phase 7)
- **THEN** it uses `ClaudeSDKClient` with `connect()`, `query()`, and `receive_response()` to enable `interrupt()` if the agent goes off-rails

### Requirement: Max turns enforced per agent type
Every SDK call SHALL specify a `max_turns` limit appropriate to the task scope.

#### Scenario: Review agents capped
- **WHEN** a plan review (Phase 4) or code review (Phase 9) agent is spawned
- **THEN** `max_turns` is set to 10

#### Scenario: Implementation agents capped
- **WHEN** an implementation agent (Phase 7) is spawned
- **THEN** `max_turns` is set to 30

#### Scenario: Exploration agents capped
- **WHEN** an exploration agent (Phase 2b) is spawned
- **THEN** `max_turns` is set to 15

#### Scenario: Minimal agents capped
- **WHEN** an inline interview (Phase 1) or PR body (Phase 11) agent is spawned
- **THEN** `max_turns` is set to 5 or 3 respectively

### Requirement: Tool subsets per agent type
Each SDK call SHALL specify `allowed_tools` restricted to the tools needed for that task type. Agents SHALL NOT receive access to tools irrelevant to their task.

#### Scenario: Review agents are read-only
- **WHEN** a plan review or code review agent is spawned
- **THEN** `allowed_tools` is restricted to `["Read", "Glob", "Grep"]` — no Edit, Write, or Bash

#### Scenario: Implementation agents get editing tools
- **WHEN** an implementation agent is spawned
- **THEN** `allowed_tools` includes `["Read", "Edit", "Write", "Bash", "Glob", "Grep"]`

#### Scenario: Interview agents get no tools
- **WHEN** an inline interview agent is spawned
- **THEN** `allowed_tools` is empty or conversation-only — no file system access

### Requirement: Model tiering by task type
SDK calls SHALL use model tiering: `sonnet` for bounded analytical tasks, `opus` for creative and implementation tasks.

#### Scenario: Sonnet for reviews and exploration
- **WHEN** the orchestrator calls Phase 1 (interview), 2b (exploration), 4 (plan review), 9 (code review), or 11 (PR body)
- **THEN** `model` is set to `"sonnet"`

#### Scenario: Opus for implementation and spec generation
- **WHEN** the orchestrator calls Phase 3 (spec generation), 7 (implementation), or 8 (test fix)
- **THEN** `model` is set to `"opus"`

### Requirement: Security policy via can_use_tool callback
Every SDK call that grants Bash or Edit access SHALL include a `can_use_tool` callback that evaluates a `SecurityPolicy`.

#### Scenario: Dangerous bash commands blocked
- **WHEN** an agent attempts to execute a Bash command matching `rm -rf /`, `git push.*--force`, `DROP TABLE`, or `git checkout main`
- **THEN** the `can_use_tool` callback returns `False` and the command is not executed

#### Scenario: File writes outside worktree blocked
- **WHEN** an agent attempts to use Edit or Write on a file path outside the worktree directory
- **THEN** the `can_use_tool` callback returns `False` and the write is blocked

#### Scenario: Irrelevant tools blocked
- **WHEN** an agent attempts to use MCP tools not relevant to code tasks (e.g., `mcp__excalidraw__*`)
- **THEN** the `can_use_tool` callback returns `False`

### Requirement: Implementation agent supports interrupt
The Phase 7 implementation agent SHALL use `ClaudeSDKClient` with streaming response. The orchestrator SHALL be able to call `interrupt()` to abort a runaway agent.

#### Scenario: Runaway agent interrupted
- **WHEN** an implementation agent exceeds expected behavior (custom guard function returns true)
- **THEN** the orchestrator calls `client.interrupt()` and the agent stops, preserving partial work

#### Scenario: Normal completion
- **WHEN** an implementation agent completes within `max_turns`
- **THEN** the orchestrator receives a `ResultMessage` with `is_success`, `total_cost_usd`, `duration_ms`, and `num_turns`
