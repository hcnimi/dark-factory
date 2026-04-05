## ADDED Requirements

### Requirement: Adversarial Evaluation with Fresh Context

The evaluator SHALL be a separate model invocation from the implementation agent.

The evaluator SHALL receive only: the intent document (with acceptance criteria) and the git diff of changes made.

The evaluator SHALL NOT have access to the implementation agent's conversation history, reasoning, or intermediate state.

#### Scenario: Clean evaluation context
- **GIVEN** a completed implementation run
- **WHEN** the evaluator is invoked
- **THEN** it receives the intent document and `git diff` against the base branch
- **AND** it does NOT receive any implementation agent messages or tool call history

### Requirement: Three-Dimension Rubric Scoring

The evaluator SHALL score the implementation on three dimensions:

1. **Intent Fidelity** (0-10): Does the implementation match what was requested? Are all acceptance criteria addressed?
2. **Correctness** (0-10): Is the code correct? Does it handle edge cases? Are there bugs, security issues, or logic errors?
3. **Integration** (0-10): Does the code integrate properly with the existing codebase? Does it follow project conventions, patterns, and style?

Each dimension SHALL include a numeric score and a narrative justification explaining the score.

The rubric SHALL be standard across all tickets (not customized per-ticket). Domain-specific dimensions MAY be added through iteration based on real-world results.

#### Scenario: High-scoring implementation
- **GIVEN** an implementation that addresses all acceptance criteria, is correct, and follows conventions
- **WHEN** the evaluator scores it
- **THEN** all three dimensions score 8-10
- **AND** each score has a justification citing specific evidence from the diff

#### Scenario: Wrong thing built well
- **GIVEN** an implementation that is correct and well-integrated but misses key acceptance criteria
- **WHEN** the evaluator scores it
- **THEN** Intent Fidelity scores low (2-4)
- **AND** Correctness scores high (8-10)
- **AND** Integration scores high (8-10)
- **AND** the justification for Intent Fidelity identifies which acceptance criteria were missed

#### Scenario: Right thing built poorly
- **GIVEN** an implementation that addresses all acceptance criteria but has bugs and ignores conventions
- **WHEN** the evaluator scores it
- **THEN** Intent Fidelity scores high (8-10)
- **AND** Correctness scores low (3-5)
- **AND** Integration scores low (3-5)
- **AND** justifications cite specific bugs and convention violations

### Requirement: Acceptance Criteria Verification

The evaluator SHALL explicitly check each acceptance criterion from the intent document against the implementation.

Each criterion SHALL be marked as: met, partially met, or not met, with evidence from the diff.

#### Scenario: All criteria met
- **GIVEN** an intent document with 4 acceptance criteria
- **WHEN** the evaluator checks the implementation
- **THEN** each criterion is individually assessed
- **AND** all 4 are marked "met" with references to the relevant code

#### Scenario: Partial implementation
- **GIVEN** an intent document with 4 acceptance criteria
- **WHEN** the evaluator checks a partial implementation (budget exhausted mid-run)
- **THEN** 2 criteria are marked "met", 1 "partially met", 1 "not met"
- **AND** each assessment includes evidence or explanation of what's missing

### Requirement: Configurable Evaluator Model

The evaluator model SHALL be configurable via project config.

The default evaluator model SHALL be Sonnet (cost-effective for most evaluations).

Complex codebases MAY configure Opus as the evaluator for deeper analysis.

#### Scenario: Default Sonnet evaluator
- **GIVEN** no evaluator model configured in `.dark-factory/config.yaml`
- **WHEN** the evaluator runs
- **THEN** it uses Sonnet

#### Scenario: Opus evaluator configured
- **GIVEN** `.dark-factory/config.yaml` contains `evaluator_model: opus`
- **WHEN** the evaluator runs
- **THEN** it uses Opus

### Requirement: Dual Output Format

The evaluator SHALL produce output in two formats:

1. **JSON report** stored at `.dark-factory/<run-id>.evaluation.json` containing: dimensional scores, per-criterion assessments, narrative feedback, metadata (model used, cost, timing)
2. **PR review comment** posted to the pull request (when PR exists) containing: a formatted human-readable summary of scores, criterion assessments, and key findings

#### Scenario: Full run with PR
- **GIVEN** a completed run that produced a pull request
- **WHEN** the evaluator finishes
- **THEN** a JSON report is written to `.dark-factory/`
- **AND** a formatted review comment is posted to the PR

#### Scenario: Evaluation without PR
- **GIVEN** a run that did not create a PR (e.g., MVP mode or `--dry-run`)
- **WHEN** the evaluator finishes
- **THEN** a JSON report is written to `.dark-factory/`
- **AND** the evaluation summary is printed to stdout

### Requirement: Standalone Evaluation

The evaluator SHALL be invocable independently via `dark-factory evaluate`.

It SHALL accept: a branch name or diff, plus an intent document (file path or inline).

This enables evaluation of any PR, not just dark-factory output.

#### Scenario: Evaluate an existing branch
- **GIVEN** a feature branch `feature/add-preferences` with changes
- **WHEN** the user runs `dark-factory evaluate feature/add-preferences --intent=intent.md`
- **THEN** the evaluator computes the diff against the base branch
- **AND** scores the changes against the provided intent document
- **AND** outputs the JSON report and prints summary to stdout

#### Scenario: Evaluate without intent
- **GIVEN** a feature branch with changes but no intent document provided
- **WHEN** the user runs `dark-factory evaluate feature/add-preferences`
- **THEN** the evaluator infers intent from commit messages and PR description (if available)
- **AND** scores on correctness and integration dimensions (intent fidelity scored as N/A)

### Requirement: Optional Re-Run on Borderline Scores

The system SHALL support an optional re-run when evaluation scores are borderline.

Borderline is defined as: any dimension scoring 5-7 out of 10.

The re-run SHALL be user-triggered (not automatic). The system presents borderline scores and offers the user the option to re-run implementation with evaluator feedback.

#### Scenario: Borderline score with user re-run
- **GIVEN** an evaluation with Intent Fidelity: 9, Correctness: 6, Integration: 8
- **WHEN** the system detects the borderline Correctness score
- **AND** the human gate after evaluation is enabled
- **THEN** the system presents the scores and asks the user if they want to re-run
- **AND** if approved, launches a new implementation run with the evaluator's feedback injected as additional context

#### Scenario: High scores, no re-run offered
- **GIVEN** an evaluation with all dimensions scoring 8+
- **WHEN** the system checks for borderline scores
- **THEN** no re-run is offered
- **AND** the system proceeds to PR creation (or completes if no PR step)

### Requirement: Human Gate After Evaluation (Configurable)

The system SHALL support a configurable human approval gate after evaluation.

When enabled, the system presents scores and asks the user to approve PR creation, request re-run, or abort.

When disabled, the system auto-proceeds based on scores: high scores create PR, low scores report and stop.

#### Scenario: Gate enabled, user approves
- **GIVEN** `gates: [eval]` in config
- **WHEN** evaluation completes with scores 8, 9, 8
- **THEN** the system presents scores and waits for user approval
- **AND** on approval, creates the PR

#### Scenario: Gate disabled, auto-proceed
- **GIVEN** `gates: []` in config
- **WHEN** evaluation completes with scores 8, 9, 8
- **THEN** the system automatically creates the PR without waiting for approval
