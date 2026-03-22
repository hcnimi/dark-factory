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
The `/dark-factory` command SHALL accept the same arguments as today: `<jira-key>`, `<file-path>`, `"<description>"`, `--dry-run`, `--resume`. The markdown command SHALL delegate to `python3 -m dark_factory` and read structured JSON output.

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

### Requirement: Incremental migration coexistence
During migration Steps 1-3, the markdown command SHALL delegate completed phases to Python and handle remaining phases itself. No phase SHALL be split across runtimes.

#### Scenario: Step 1 partial delegation
- **WHEN** Step 1 is deployed
- **THEN** Phases 0, 5, 6, 10 execute via `python3 -m dark_factory`, and Phases 1-4, 7-9, 11 execute in the markdown command

#### Scenario: Step 4 full delegation
- **WHEN** Step 4 is deployed
- **THEN** the markdown command is a thin launcher (~50 lines) that calls `python3 -m dark_factory "$ARGUMENTS"` and all phases execute in Python
