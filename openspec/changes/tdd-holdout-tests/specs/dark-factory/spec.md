## MODIFIED Requirements

### Requirement: Test Verification
The command SHALL run the target repo's test suite after implementation completes.
Test commands are detected from the repo's CLAUDE.md. If tests fail, the command
analyzes and fixes up to 3 times before stopping.

After the main test suite passes, the command SHALL run hold-out tests (generated in Phase 6.5) as a separate verification step using the running Python interpreter (`sys.executable`), not a hardcoded `python3`, to ensure correct interpreter resolution across pyenv/Homebrew environments. Hold-out test failures SHALL produce a warning with details, NOT a hard pipeline failure. Hold-out results SHALL be surfaced to the human for review.

#### Scenario: Tests pass
- **GIVEN** implementation is complete
- **WHEN** the test suite runs
- **THEN** all tests pass and the command proceeds

#### Scenario: Tests fail and are fixed
- **GIVEN** implementation introduced a test failure
- **WHEN** the test suite fails
- **THEN** the command analyzes the failure, applies a fix, and re-runs
- **AND** this retry happens up to 3 times

#### Scenario: Tests fail after 3 retries
- **GIVEN** tests continue to fail after 3 fix attempts
- **WHEN** the third retry fails
- **THEN** the command stops and reports the failures to the human

#### Scenario: Hold-out tests pass
- **GIVEN** the main test suite passes and hold-out tests exist
- **WHEN** hold-out tests are executed
- **THEN** all hold-out tests pass
- **AND** the pipeline proceeds normally

#### Scenario: Hold-out tests fail (interactive)
- **GIVEN** the main test suite passes but one or more hold-out tests fail
- **WHEN** hold-out test results are evaluated and stdin is a TTY
- **THEN** the pipeline produces a WARNING (not an error)
- **AND** the warning includes which hold-out tests failed and their expected behavior
- **AND** the human is prompted to review: accept (proceed), investigate (pause), or abort

#### Scenario: Hold-out tests fail (non-interactive)
- **GIVEN** the main test suite passes but one or more hold-out tests fail
- **WHEN** hold-out test results are evaluated and stdin is not a TTY (e.g., SDK subprocess)
- **THEN** the pipeline defaults to "investigate" (safe pause) without blocking on input
- **AND** the warning is printed to stderr for the human to review after the process exits

#### Scenario: Hold-out test interpreter portability
- **GIVEN** hold-out tests need to be executed
- **WHEN** the pipeline invokes pytest for hold-out tests
- **THEN** it uses `sys.executable` (the running interpreter) instead of a hardcoded `python3` to ensure the correct virtual environment and installed packages are used

#### Scenario: No hold-out tests generated
- **GIVEN** Phase 6.5 produced an empty hold-out test set
- **WHEN** Phase 8 reaches the hold-out verification step
- **THEN** the step is skipped and the pipeline proceeds normally
