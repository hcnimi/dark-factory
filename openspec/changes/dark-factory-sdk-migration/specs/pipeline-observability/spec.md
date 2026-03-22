## ADDED Requirements

### Requirement: Per-phase timing recorded
The orchestrator SHALL record wall-clock duration for every phase and persist it in the JSON state file.

#### Scenario: Phase timing captured
- **WHEN** a phase completes (success or failure)
- **THEN** `phase_timings[phase_number]` contains the elapsed seconds (float) and the state file is updated

#### Scenario: Timing survives resume
- **WHEN** a pipeline resumes from a saved state
- **THEN** prior phase timings are preserved and new phase timings are appended

### Requirement: Per-phase cost tracked
The orchestrator SHALL accumulate `total_cost_usd` from each SDK `ResultMessage` and persist cumulative cost in the JSON state file.

#### Scenario: Cost accumulated from SDK calls
- **WHEN** an SDK call returns a `ResultMessage`
- **THEN** `result_msg.total_cost_usd` is added to `state.total_cost_usd` and the state file is updated

#### Scenario: Deterministic phases report zero cost
- **WHEN** a deterministic phase (0, 5, 6, 10) completes
- **THEN** no cost is added to `state.total_cost_usd` for that phase

### Requirement: Turn count tracked per agent
The orchestrator SHALL record `num_turns` from each SDK `ResultMessage` alongside the phase it belongs to.

#### Scenario: Turn count persisted
- **WHEN** an SDK call completes
- **THEN** the state file records `num_turns` for that phase, enabling analysis of which agents are most expensive in API round-trips

### Requirement: Event logging for pipeline diagnosis
The orchestrator SHALL log phase transitions and key events to enable post-mortem diagnosis of failures like SDLC-2888 (silent death).

#### Scenario: Phase transition logged
- **WHEN** the orchestrator transitions from one phase to the next
- **THEN** a log entry is written with timestamp, phase number, phase name, and outcome (success/failure/skipped)

#### Scenario: Pipeline crash produces diagnostic trail
- **WHEN** the pipeline crashes unexpectedly
- **THEN** the JSON state file contains the last completed phase, timing data up to that point, and the current phase that was in progress — providing enough context to diagnose the failure

### Requirement: Pipeline summary on completion
The orchestrator SHALL print a summary after Phase 11 (or on any terminal failure) showing per-phase timing, total cost, and turn counts.

#### Scenario: Success summary
- **WHEN** the pipeline completes Phase 11 and creates a PR
- **THEN** the orchestrator prints a table showing each phase's duration, cost, and turn count, plus totals

#### Scenario: Failure summary
- **WHEN** the pipeline stops due to a phase failure
- **THEN** the orchestrator prints completed phase timings, the failing phase, and cumulative cost up to the failure point
