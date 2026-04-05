## ADDED Requirements

### Requirement: Intent Clarification from Multiple Sources

The system SHALL accept input from three source types: Jira ticket identifiers, local file paths (spec files, ideation output), and inline text descriptions.

The system SHALL classify the input source type and extract intent information appropriate to each format.

#### Scenario: Jira ticket input
- **GIVEN** a Jira ticket identifier (e.g., DPPT-1234)
- **WHEN** the intent clarifier processes the input
- **THEN** it reads the ticket summary, description, and acceptance criteria via Jira API
- **AND** produces a structured intent document

#### Scenario: Spec file input
- **GIVEN** a local file path to a spec or ideation document
- **WHEN** the intent clarifier processes the input
- **THEN** it reads the file contents and extracts intent, requirements, and any existing acceptance criteria
- **AND** produces a structured intent document

#### Scenario: Inline description input
- **GIVEN** a text description provided as a CLI argument or through the Claude Code conversation
- **WHEN** the intent clarifier processes the input
- **THEN** it parses the description to extract intent
- **AND** produces a structured intent document

### Requirement: Conversational Gap-Filling

The system SHALL detect when input is insufficiently defined to produce testable acceptance criteria.

When gaps are detected, the system SHALL conduct a conversational interview via Claude Code native UX (AskUserQuestion) to fill those gaps.

The system SHALL skip the interview when input is already well-defined (e.g., a spec file with explicit acceptance criteria).

#### Scenario: Well-defined Jira ticket
- **GIVEN** a Jira ticket with summary, description, and 3+ acceptance criteria
- **WHEN** the intent clarifier processes the input
- **THEN** it produces the structured intent document without interviewing the user

#### Scenario: Vague inline description
- **GIVEN** an inline description "add user preferences endpoint"
- **WHEN** the intent clarifier processes the input
- **THEN** it detects missing information (scope, data model, API contract, error handling)
- **AND** asks targeted clarifying questions via Claude Code conversation
- **AND** incorporates answers into the structured intent document

#### Scenario: Partially defined input
- **GIVEN** a spec file with clear intent but no acceptance criteria
- **WHEN** the intent clarifier processes the input
- **THEN** it asks only for the missing acceptance criteria, not for information already present

### Requirement: Structured Intent Output

The system SHALL produce a structured intent document containing:
- Intent summary (what to build and why)
- Testable acceptance criteria (concrete, verifiable conditions)

The standard evaluation rubric (intent fidelity, correctness, integration) SHALL be applied by the evaluator, not generated per-ticket by the clarifier.

#### Scenario: Intent document structure
- **GIVEN** any valid input source
- **WHEN** the intent clarifier completes processing
- **THEN** the output document contains an intent summary section
- **AND** the output document contains at least one testable acceptance criterion
- **AND** each acceptance criterion is specific enough to verify programmatically or by inspection

### Requirement: Scope Validation and Auto-Decomposition

The system SHALL validate that the feature scope is right-sized for a single agent run.

The system SHALL use acceptance criteria count as the primary scope signal and model self-assessment as a secondary check.

When scope is too large, the system SHALL automatically decompose the ticket into sequential sub-runs, each with its own intent document.

#### Scenario: Right-sized feature
- **GIVEN** an input that produces 4 acceptance criteria spanning one logical concern
- **WHEN** the scope validator runs
- **THEN** it determines the feature is right-sized
- **AND** proceeds with a single implementation run

#### Scenario: Oversized feature
- **GIVEN** an input that produces 12 acceptance criteria spanning 3 independent concerns
- **WHEN** the scope validator runs
- **THEN** it determines the feature should be decomposed
- **AND** produces 3 separate intent documents, ordered so later sub-runs can build on earlier ones
- **AND** queues sequential sub-runs

#### Scenario: Borderline scope with model assessment
- **GIVEN** an input that produces 7 acceptance criteria
- **WHEN** the scope validator runs
- **THEN** it asks the model to assess whether implementation is feasible in a single session
- **AND** uses the model's assessment to decide between single run and decomposition

### Requirement: Human Gate After Intent (Configurable)

The system SHALL support a configurable human approval gate after intent clarification.

When the gate is enabled, the system SHALL present the intent document and acceptance criteria for human review before proceeding to implementation.

When the gate is disabled, the system SHALL proceed automatically.

#### Scenario: Gate enabled
- **GIVEN** the project config has `gates: [intent]`
- **WHEN** the intent clarifier completes
- **THEN** the system presents the intent document to the user
- **AND** waits for approval, modification, or abort

#### Scenario: Gate disabled
- **GIVEN** the project config has `gates: []`
- **WHEN** the intent clarifier completes
- **THEN** the system proceeds directly to implementation without human review
