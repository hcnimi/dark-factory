## ADDED Requirements

### Requirement: Python state machine owns phase transitions
The orchestrator SHALL execute phases as Python function calls. The LLM SHALL NOT determine which phase to execute next — phase sequencing MUST be controlled by `pipeline.py`.

#### Scenario: Normal pipeline execution
- **WHEN** the pipeline runs from Phase 0 through Phase 11
- **THEN** each phase transition is a Python function call that returns a typed result, and the next phase is selected by code (not LLM inference)

#### Scenario: Phase failure halts pipeline
- **WHEN** any phase function raises an exception
- **THEN** the orchestrator saves state to JSON and stops — no subsequent phases execute

### Requirement: CLI interface preserved
The `/dark-factory` command SHALL accept the same arguments as today: `<jira-key>`, `<file-path>`, `"<description>"`, `--dry-run`, `--resume`. The markdown command SHALL delegate to the `dark-factory run` CLI entry point (installed via `pip install -e .`) and read structured JSON output. The entry point SHALL be used instead of `python3 -m dark_factory` to ensure correct interpreter resolution through pyenv shims and Homebrew.

#### Scenario: Jira key input
- **WHEN** user runs `/dark-factory SDLC-123`
- **THEN** `cli.py` parses the argument as a Jira key via regex `[A-Z]+-\d+` and routes to Jira ingestion

#### Scenario: File path input
- **WHEN** user runs `/dark-factory specs/my-feature.md`
- **THEN** `cli.py` detects a file path (contains `/` or `.`) and routes to file ingestion

#### Scenario: Inline description input
- **WHEN** user runs `/dark-factory "add dark mode toggle"`
- **THEN** `cli.py` treats the quoted string as an inline description and routes to LLM interview

#### Scenario: Resume flag
- **WHEN** user runs `/dark-factory SDLC-123 --resume`
- **THEN** `cli.py` loads the existing JSON state file from `.dark-factory/sdlc-123.json` and resumes from the last completed phase

### Requirement: JSON state management
Pipeline state SHALL be a Python dataclass serialized to `.dark-factory/<KEY>.json`. The LLM SHALL NOT read or write this file — only the orchestrator code owns state transitions.

#### Scenario: State saved after each phase
- **WHEN** a phase completes successfully
- **THEN** the orchestrator updates `current_phase`, appends to `completed_phases`, records `phase_timings`, and writes the JSON state file

#### Scenario: Resume from JSON state
- **WHEN** `--resume` is passed and a state file exists for the source key
- **THEN** the orchestrator loads the state file and resumes execution from `current_phase`

#### Scenario: State preserved on failure
- **WHEN** a phase fails with an exception
- **THEN** the orchestrator writes the current state to JSON before raising, enabling future `--resume`

### Requirement: Deterministic phases execute without LLM
Phases 0 (tool discovery/arg parsing), 5 (human checkpoint), 6 (beads issue creation), and 10 (local dev verification) SHALL execute as pure Python functions with zero LLM token consumption.

#### Scenario: Phase 0 arg parsing
- **WHEN** Phase 0 executes
- **THEN** argument parsing, tool availability checks, session detection, and input routing complete without any SDK or LLM call

#### Scenario: Phase 6 beads issue creation
- **WHEN** Phase 6 executes with a parsed tasks list
- **THEN** `bd create` CLI commands are invoked via `subprocess` for each task, and issue IDs are captured from JSON output — no LLM involved

### Requirement: Human gates use pause-exit-resume in non-interactive mode
The pipeline runs inside a Claude Code SDK subprocess where stdin is not a TTY. Human decision gates (Phases 5, 8 holdout, 10) SHALL NOT call `input()` when `sys.stdin.isatty()` is False. Instead, they SHALL save state and exit with `--resume` instructions, following the pause-exit-resume pattern for human-in-the-loop agent harnesses.

#### Scenario: Phase 5 non-interactive pause
- **WHEN** Phase 5 (plan review) executes and stdin is not a TTY
- **THEN** the orchestrator saves state and exits with a message instructing the human to review the spec files and resume with `dark-factory run <source> --resume`

#### Scenario: Phase 8 holdout gate non-interactive default
- **WHEN** Phase 8 holdout tests fail and stdin is not a TTY
- **THEN** the pipeline defaults to "investigate" (safe pause) rather than blocking on input, preserving human review without blocking the agent harness

#### Scenario: Phase 10 always pauses
- **WHEN** Phase 10 (local dev verification) executes
- **THEN** the orchestrator saves state, prints the worktree path and branch name, and exits — regardless of whether stdin is a TTY. The human verifies locally, then runs `dark-factory run <source> --resume` to continue to Phase 11

### Requirement: Dry-run mode skips all SDK calls
When `--dry-run` is active, all phases that invoke SDK agents SHALL short-circuit with empty output and zero cost. Deterministic phases execute normally. This enables testing the full pipeline flow without consuming LLM tokens.

#### Scenario: SDK phase in dry-run
- **WHEN** any SDK-calling phase (1.5, 2b, 3, 4, 6.5, 7, 8, 9, 11) executes with `--dry-run`
- **THEN** the agent wrapper returns empty messages, zero cost, and zero turns without invoking the SDK

#### Scenario: Deterministic phase in dry-run
- **WHEN** a deterministic phase (0, 1, 2a, 5, 6, 10) executes with `--dry-run`
- **THEN** the phase executes normally (these phases consume zero LLM tokens regardless)

### Requirement: Incremental migration coexistence
During migration Steps 1-3, the markdown command SHALL delegate completed phases to Python and handle remaining phases itself. No phase SHALL be split across runtimes.

#### Scenario: Step 1 partial delegation
- **WHEN** Step 1 is deployed
- **THEN** Phases 0, 5, 6, 10 execute via `dark-factory run`, and Phases 1-4, 7-9, 11 execute in the markdown command

#### Scenario: Step 4 full delegation
- **WHEN** Step 4 is deployed
- **THEN** the markdown command is a thin launcher (~50 lines) that calls `dark-factory run "$ARGUMENTS"` and all phases execute in Python
