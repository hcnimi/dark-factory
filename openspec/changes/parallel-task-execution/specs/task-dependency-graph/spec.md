## ADDED Requirements

### Requirement: Parse dependency markers from task lines
The system SHALL extract dependency markers (`[P]` and `[depends: N, ...]`) from each task line in tasks.md. A task marked `[P]` SHALL be classified as independent. A task marked `[depends: N]` SHALL be classified as dependent on task number N. Multiple dependencies SHALL be supported via comma-separated values (e.g., `[depends: 1, 3]`).

#### Scenario: Independent task marker
- **WHEN** a task line contains `[P]` (e.g., `1. [P] Add validation endpoint`)
- **THEN** the task is classified as independent with no dependencies

#### Scenario: Single dependency marker
- **WHEN** a task line contains `[depends: 2]`
- **THEN** the task is classified as dependent on task 2

#### Scenario: Multiple dependency markers
- **WHEN** a task line contains `[depends: 1, 3]`
- **THEN** the task is classified as dependent on both task 1 and task 3

#### Scenario: No marker (backward compatibility)
- **WHEN** a task line has no `[P]` or `[depends: N]` marker
- **THEN** the task SHALL default to sequential execution, treated as depending on the previous task (`[depends: N-1]` where N is the current task's 1-based index)

#### Scenario: First task with no marker
- **WHEN** the first task (index 1) has no marker
- **THEN** the task SHALL be treated as independent (no previous task to depend on)

### Requirement: Build a directed acyclic graph from parsed tasks
The system SHALL construct a DAG where nodes are task numbers (1-based) and edges represent "depends on" relationships. The DAG builder SHALL validate the graph and reject invalid inputs.

#### Scenario: Valid DAG construction
- **WHEN** tasks are parsed with markers `[1: P, 2: P, 3: depends 1,2, 4: P]`
- **THEN** the DAG SHALL contain edges 3→1 and 3→2, with nodes 1, 2, and 4 having no incoming dependency edges

#### Scenario: Cycle detection
- **WHEN** task markers create a cycle (e.g., task 1 depends on 3, task 3 depends on 1)
- **THEN** the system SHALL raise a `CyclicDependencyError` and refuse to build the graph

#### Scenario: Invalid reference
- **WHEN** a `[depends: N]` references a task number N that does not exist
- **THEN** the system SHALL raise a `InvalidDependencyError` identifying the missing task number

#### Scenario: Self-reference
- **WHEN** a task depends on itself (e.g., task 2 has `[depends: 2]`)
- **THEN** the system SHALL raise a `CyclicDependencyError`

### Requirement: Resolve execution waves from the DAG
The system SHALL compute an ordered list of waves via topological sort. Each wave contains tasks whose dependencies are all satisfied by prior waves. Tasks within a wave MAY execute concurrently.

#### Scenario: All independent tasks
- **WHEN** all tasks are marked `[P]`
- **THEN** the system SHALL produce a single wave containing all tasks

#### Scenario: Linear dependency chain
- **WHEN** tasks form a chain (1→2→3→4, each depending on the previous)
- **THEN** the system SHALL produce 4 waves, each containing exactly one task

#### Scenario: Mixed independence and dependencies
- **WHEN** tasks are: `[1: P, 2: P, 3: depends 1,2, 4: P, 5: depends 3]`
- **THEN** wave 0 SHALL contain tasks 1, 2, 4; wave 1 SHALL contain task 3; wave 2 SHALL contain task 5

#### Scenario: Diamond dependency
- **WHEN** tasks are: `[1: P, 2: depends 1, 3: depends 1, 4: depends 2,3]`
- **THEN** wave 0 SHALL contain task 1; wave 1 SHALL contain tasks 2 and 3; wave 2 SHALL contain task 4

### Requirement: Map task numbers to issue IDs
The system SHALL accept a mapping from 1-based task numbers to issue IDs (created in Phase 6) and produce waves containing issue IDs instead of task numbers. This mapping is applied after wave resolution.

#### Scenario: Task-to-issue mapping
- **WHEN** wave resolution produces `[[1, 3], [2]]` and the mapping is `{1: "beads-001", 2: "beads-002", 3: "beads-003"}`
- **THEN** the output SHALL be `[["beads-001", "beads-003"], ["beads-002"]]`
