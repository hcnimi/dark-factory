## ADDED Requirements

### Requirement: LLM calls use claude-code-sdk
All LLM invocations SHALL use the `claude-code-sdk` Python package (`query()` or `ClaudeSDKClient`). The orchestrator SHALL NOT use `claude -p` subprocesses or direct Anthropic API calls.

#### Scenario: SDK query for bounded tasks
- **WHEN** the orchestrator needs a bounded LLM call (exploration, review, PR body)
- **THEN** it uses `query()` with `ClaudeCodeOptions` specifying `model`, `max_turns`, `allowed_tools`, and `cwd`

#### Scenario: SDK client for agents with edit tools
- **WHEN** the orchestrator spawns an agent that has edit tools and a security policy — Phase 7 (implementation) or Phase 8 (test fix)
- **THEN** it uses `ClaudeSDKClient` with `connect()` and `receive_response()` to enable `interrupt()` if the agent goes off-rails and to support the `can_use_tool` callback, which requires streaming mode

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
- **THEN** `max_turns` is set to 5 (reduced from 15 because context-engineering layers — import graph, test mapping, symbol context — front-load structural analysis into Phase 2a)

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

#### Scenario: Scaffold agents get full tool access
- **WHEN** a Phase 3 scaffold agent is spawned
- **THEN** `allowed_tools` is left unrestricted (empty list `[]` in the SDK means "no restriction" — the `--allowedTools` flag is not passed to the CLI) so the agent can write proposal.md, spec.md, and tasks.md directly to disk using the Write tool. The orchestrator checks disk first for model-written files and falls back to text parsing only if files are missing.

### Requirement: Model tiering by task type
SDK calls SHALL use model tiering: `sonnet` for bounded analytical tasks, `opus` for creative and implementation tasks.

#### Scenario: Sonnet for reviews, exploration, and scaffolding
- **WHEN** the orchestrator calls Phase 1 (interview), 2b (exploration), 3 (scaffold/spec generation), 4 (plan review), 6.5 (test generation), 9 (code review), or 11 (PR body)
- **THEN** `model` is set to `"sonnet"`

#### Scenario: Opus for implementation and fix
- **WHEN** the orchestrator calls Phase 7 (implementation) or 8 (test fix)
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

### Requirement: SDK message parsing tolerates unknown message types
The orchestrator SHALL patch the SDK message parser to skip unrecognized message types (e.g., `rate_limit_event`) rather than crashing. Text extraction from SDK messages SHALL handle structured content blocks (accessing `TextBlock.text`) rather than stringifying the content object, which produces unusable representations.

#### Scenario: Unknown message type during streaming
- **WHEN** the SDK stream yields a message type not in the parser's known set (e.g., `rate_limit_event`)
- **THEN** the patched parser returns `None` and the orchestrator skips the message without error

#### Scenario: Structured content block extraction
- **WHEN** an SDK message contains a list of content blocks with `.text` attributes
- **THEN** the orchestrator extracts each block's `.text` string individually, rather than calling `str()` on the content list

### Requirement: Streaming prompt required for can_use_tool
When a `can_use_tool` callback is configured on `ClaudeSDKClient`, the SDK requires the prompt to be an async iterable (streaming mode), not a plain string. The orchestrator SHALL wrap string prompts in an async generator before calling `client.connect()`.

#### Scenario: String prompt with security policy
- **WHEN** `_sdk_client_query` receives a string prompt and a `SecurityPolicy` is active
- **THEN** the orchestrator wraps the string in an async generator yielding a single user message, enabling the `can_use_tool` callback to function

### Requirement: Edit-tool agents support interrupt
Phase 7 (implementation) and Phase 8 (test fix) agents SHALL use `ClaudeSDKClient` with streaming response. The orchestrator SHALL be able to call `interrupt()` to abort a runaway agent.

#### Scenario: Runaway agent interrupted
- **WHEN** an implementation or fix agent exceeds expected behavior (custom guard function returns true)
- **THEN** the orchestrator calls `client.interrupt()` and the agent stops, preserving partial work

#### Scenario: Normal completion
- **WHEN** an implementation or fix agent completes within `max_turns`
- **THEN** the orchestrator receives a `ResultMessage` with `is_success`, `total_cost_usd`, `duration_ms`, and `num_turns`
