## ADDED Requirements

### Requirement: Single Opus Agent Lifecycle

The system SHALL launch a single Opus agent for each implementation run.

The agent SHALL have access to full edit tools (Read, Edit, Write, Bash, Glob, Grep).

The system SHALL enforce a cost budget for the entire run, terminating the agent if the budget is exceeded.

#### Scenario: Normal implementation
- **GIVEN** an intent document with acceptance criteria
- **WHEN** the infrastructure wrapper launches implementation
- **THEN** it spawns a single Opus SDK agent
- **AND** provides the intent document as context
- **AND** the agent drives exploration, planning, and implementation freely

#### Scenario: Budget exceeded
- **GIVEN** an implementation run in progress
- **WHEN** the cumulative cost exceeds the configured budget
- **THEN** the system terminates the agent
- **AND** commits partial work
- **AND** proceeds to evaluation of the partial result

### Requirement: Security Policy

The system SHALL enforce security boundaries on all agent tool calls:
- Write boundary: agent can only modify files within the worktree (or repo root if `--in-place`)
- Blocked command patterns: `rm -rf /`, `git push --force`, `git reset --hard`, `DROP TABLE`, `git checkout main/master`
- Blocked tools: tools that could cause external side effects outside the project scope

The security policy SHALL be enforced programmatically via the SDK's `can_use_tool` callback, not via prompt instructions.

#### Scenario: Write outside boundary
- **GIVEN** an agent running in a worktree at `/tmp/dark-factory-worktree-abc`
- **WHEN** the agent attempts to edit `/Users/home/.bashrc`
- **THEN** the tool call is blocked
- **AND** the agent receives an error message explaining the boundary

#### Scenario: Dangerous command blocked
- **GIVEN** an agent running implementation
- **WHEN** the agent attempts to run `git push --force`
- **THEN** the command is blocked before execution
- **AND** the agent receives an error explaining the blocked pattern

### Requirement: Worktree Isolation

The system SHALL create a git worktree for each implementation run by default.

The system SHALL support an `--in-place` flag to work directly in the user's repository.

The worktree SHALL be on a feature branch created from the current HEAD.

The system SHALL clean up worktrees on completion or unexpected exit (via atexit handler).

#### Scenario: Default worktree isolation
- **GIVEN** a `dark-factory run` invocation without `--in-place`
- **WHEN** the infrastructure wrapper initializes
- **THEN** it creates a git worktree on a new feature branch
- **AND** all implementation happens in the worktree
- **AND** the worktree is cleaned up after the run completes

#### Scenario: In-place execution
- **GIVEN** a `dark-factory run --in-place` invocation
- **WHEN** the infrastructure wrapper initializes
- **THEN** it creates a feature branch in the user's repository
- **AND** implementation happens directly in the user's working tree

#### Scenario: Crash cleanup
- **GIVEN** an implementation run in a worktree
- **WHEN** the process terminates unexpectedly
- **THEN** the atexit handler removes the worktree
- **AND** the feature branch is preserved for recovery

### Requirement: Continuous State Checkpointing

The system SHALL checkpoint state after each git commit the agent makes during implementation.

State SHALL be serialized to `.dark-factory/<run-id>.json`.

The system SHALL support `--resume` to continue from the last checkpoint.

#### Scenario: Checkpoint on commit
- **GIVEN** an implementation agent running
- **WHEN** the agent makes a git commit
- **THEN** the harness captures the current state (cost, files modified, commit SHA, elapsed time)
- **AND** serializes it to the state file

#### Scenario: Resume after failure
- **GIVEN** a previous run that failed mid-implementation with state file present
- **WHEN** the user runs `dark-factory run <source> --resume`
- **THEN** the system restores state from the checkpoint
- **AND** launches the Opus agent with context about what was already completed
- **AND** the agent continues from where it left off

### Requirement: Hooks Isolation

The system SHALL disable user-defined Claude Code hooks in SDK subprocesses.

This SHALL be achieved by injecting a settings override that empties the hooks configuration.

#### Scenario: User hooks present
- **GIVEN** the user has custom hooks configured in their Claude Code settings
- **WHEN** the harness launches an SDK agent
- **THEN** the agent runs without those hooks active
- **AND** the user's hook configuration is not modified

### Requirement: Pre-Flight Environment Checks

The system SHALL run lightweight pre-flight checks before launching the implementation agent:
1. Test runner detection: identify the test command for the project
2. Convention detection: detect linters, formatters, CI configs
3. CLAUDE.md validation: check presence and content of project instructions
4. Dependency verification: verify project dependencies can be installed
5. Build check: verify the project builds successfully

Pre-flight failures SHALL be reported with actionable guidance. Critical failures (project doesn't build) SHALL block implementation. Non-critical failures (no CLAUDE.md) SHALL warn.

#### Scenario: All checks pass
- **GIVEN** a well-configured project with CLAUDE.md, passing build, and running tests
- **WHEN** pre-flight checks execute
- **THEN** all checks pass
- **AND** detected conventions (test command, linter config) are injected as context for the implementation agent

#### Scenario: Build failure
- **GIVEN** a project where `npm install && npm run build` fails
- **WHEN** pre-flight checks execute
- **THEN** the build check fails
- **AND** the system reports the build error with actionable guidance
- **AND** implementation is blocked

#### Scenario: Missing CLAUDE.md
- **GIVEN** a project without a CLAUDE.md file
- **WHEN** pre-flight checks execute
- **THEN** the system warns that conventions are undocumented
- **AND** implementation proceeds with the warning noted

### Requirement: Hybrid Test Verification

The implementation agent SHALL have access to test execution via Bash tool (self-directed TDD).

After the implementation agent completes, the harness SHALL run a final deterministic test verification.

If the final verification fails, the harness SHALL re-enter the implementation agent with the test failure output for one bounded retry.

If the retry also fails, the harness SHALL proceed to evaluation with the partial/failing state.

#### Scenario: Tests pass on final verification
- **GIVEN** the implementation agent has completed its work
- **WHEN** the harness runs the detected test command
- **THEN** tests pass
- **AND** the system proceeds to evaluation

#### Scenario: Tests fail, retry succeeds
- **GIVEN** the implementation agent has completed its work
- **WHEN** the harness runs the detected test command
- **AND** tests fail
- **THEN** the harness feeds the test failure output back to the implementation agent
- **AND** the agent fixes the failures within one additional attempt
- **AND** the harness re-runs the test command
- **AND** tests pass
- **AND** the system proceeds to evaluation

#### Scenario: Tests fail, retry fails
- **GIVEN** the implementation agent has completed its work
- **WHEN** the harness runs the detected test command and tests fail
- **AND** the retry also fails
- **THEN** the system proceeds to evaluation with the failing state
- **AND** the evaluation report reflects the test failures

### Requirement: Full Observability Logging

The system SHALL log every SDK tool call with: tool name, arguments, result summary, cost, and elapsed time.

Logs SHALL be written to `.dark-factory/<run-id>.events.jsonl` in JSONL format.

The system SHALL track and report: total cost, total elapsed time, files modified, commits made, and final evaluation scores.

#### Scenario: Tool call logged
- **GIVEN** the implementation agent calls the Edit tool
- **WHEN** the tool call completes
- **THEN** a JSONL event is written with tool name, target file, cost of the underlying API call, and elapsed time

#### Scenario: Run summary
- **GIVEN** a completed dark-factory run
- **WHEN** the run finishes
- **THEN** a summary event is written with total cost, elapsed time, files modified, commits made, and evaluation scores
