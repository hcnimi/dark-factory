## ADDED Requirements

### Requirement: Spec-to-Test Generation Phase
The pipeline SHALL execute a test generation phase (Phase 6.5) after issue creation (Phase 6) and before implementation (Phase 7). Phase 6.5 SHALL invoke a Sonnet SDK agent that reads the OpenSpec change artifacts (proposal.md, spec files with Gherkin scenarios) and generates test code.

#### Scenario: Test generation from spec with Gherkin scenarios
- **GIVEN** a completed Phase 6 with an OpenSpec change containing spec files with Gherkin scenarios
- **WHEN** Phase 6.5 executes
- **THEN** the Sonnet agent generates test code that maps each Gherkin scenario to at least one test case
- **AND** tests follow the target project's testing conventions (framework, directory structure, naming)

#### Scenario: Spec with no testable scenarios
- **GIVEN** an OpenSpec change whose spec files contain no Gherkin scenarios (e.g., documentation-only change)
- **WHEN** Phase 6.5 executes
- **THEN** Phase 6.5 completes with empty test sets and proceeds to Phase 7 without error

#### Scenario: Phase 6.5 SDK failure
- **GIVEN** the Sonnet SDK call fails (timeout, API error)
- **WHEN** Phase 6.5 encounters the error
- **THEN** the pipeline raises a PipelineError for phase 6.5
- **AND** state is persisted for --resume

---

### Requirement: Visible and Hold-Out Test Split
Phase 6.5 SHALL produce two distinct test sets from the generated tests:
- **Visible tests**: provided to the Phase 7 implementation agent as TDD targets
- **Hold-out tests**: hidden from the Phase 7 agent, used only in Phase 8 verification

The split SHALL be performed by the Sonnet agent based on scenario coverage: visible tests cover the primary happy-path and core error scenarios; hold-out tests cover edge cases, boundary conditions, and secondary error paths.

#### Scenario: Tests split into visible and hold-out sets
- **GIVEN** a spec with 6 Gherkin scenarios (2 happy path, 2 error, 2 edge case)
- **WHEN** Phase 6.5 generates tests
- **THEN** visible tests cover the 2 happy-path and 2 error scenarios
- **AND** hold-out tests cover the 2 edge-case scenarios
- **AND** no test appears in both sets

#### Scenario: Spec with single scenario
- **GIVEN** a spec with only 1 Gherkin scenario
- **WHEN** Phase 6.5 generates tests
- **THEN** the test is placed in the visible set
- **AND** the hold-out set is empty

---

### Requirement: Test Artifact Persistence
Phase 6.5 SHALL write generated tests as files in the worktree's test directory and record their paths in PipelineState.

The visible test files SHALL be named with a `visible_tests_` prefix. The hold-out test files SHALL be named with a `holdout_tests_` prefix. Both SHALL use the pipeline source ID to ensure uniqueness.

#### Scenario: Test files written to worktree
- **GIVEN** Phase 6.5 has generated visible and hold-out tests
- **WHEN** the orchestrator persists the test artifacts
- **THEN** visible test files are written to the project's test directory with `visible_tests_` prefix
- **AND** hold-out test files are written with `holdout_tests_` prefix
- **AND** `PipelineState.visible_test_paths` contains the paths of visible test files
- **AND** `PipelineState.holdout_test_paths` contains the paths of hold-out test files

#### Scenario: Test directory detection
- **GIVEN** a project with tests in `tests/` (Python) or `__tests__/` (JS)
- **WHEN** Phase 6.5 needs to write test files
- **THEN** the orchestrator detects the correct test directory from project conventions
- **AND** writes test files to that directory

---

### Requirement: Visible Test Injection into Implementation Prompt
Phase 7 SHALL include visible test file paths and content in the implementation agent's prompt. The prompt SHALL instruct the agent to make the visible tests pass without modifying them.

#### Scenario: Implementation agent receives visible tests
- **GIVEN** Phase 6.5 produced visible tests at `tests/visible_tests_sdlc-123.py`
- **WHEN** Phase 7 builds the implementation prompt for an issue
- **THEN** the prompt includes the visible test file paths and their content
- **AND** the prompt instructs: "Your implementation MUST make these tests pass. Do NOT modify these test files."

#### Scenario: No visible tests generated
- **GIVEN** Phase 6.5 produced an empty visible test set
- **WHEN** Phase 7 builds the implementation prompt
- **THEN** the prompt does not include a TDD section
- **AND** Phase 7 proceeds with its existing behavior (agent writes its own tests)
