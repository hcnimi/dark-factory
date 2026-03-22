## ADDED Requirements

### Requirement: Jira Ticket Ingestion
The command SHALL accept a Jira ticket key as its primary argument and fetch
ticket details (summary, description, type, priority, acceptance criteria)
via Atlassian MCP tools.

The command SHALL stop and inform the user if the ticket description lacks
sufficient detail to proceed.

#### Scenario: Valid ticket with sufficient detail
- **GIVEN** a Jira ticket key "SDLC-123" with a description containing acceptance criteria
- **WHEN** the user runs `/dark-factory SDLC-123`
- **THEN** the command fetches the ticket and proceeds to exploration

#### Scenario: Ticket with insufficient detail
- **GIVEN** a Jira ticket key "SDLC-456" with an empty or vague description
- **WHEN** the user runs `/dark-factory SDLC-456`
- **THEN** the command stops and tells the user the ticket needs more detail

#### Scenario: Invalid ticket key
- **GIVEN** an invalid ticket key "not-a-ticket"
- **WHEN** the user runs `/dark-factory not-a-ticket`
- **THEN** the command reports the invalid format and stops

---

### Requirement: Autonomous Codebase Exploration
The command SHALL explore the target repository to understand enough context
to write a spec and implementation plan. The agent decides what to explore
and how deep to go based on the ticket content -- no prescriptive steps.

#### Scenario: Agent explores relevant areas
- **GIVEN** a ticket about a bug in the SDLC Portal plugin
- **WHEN** the command reaches the exploration phase
- **THEN** the agent reads relevant source files, tests, and patterns
  without human direction on which files to read

---

### Requirement: OpenSpec Change Generation
The command SHALL generate a valid OpenSpec change in the target repo under
`openspec/changes/dark-factory-<jira-key>/` containing:
- `proposal.md` -- why and what, derived from the Jira ticket
- `tasks.md` -- implementation checklist mapping to beads issues
- `specs/<capability>/spec.md` -- requirements with Gherkin scenarios

The generated change MUST pass `openspec validate <change-id> --strict`.

#### Scenario: Spec generated for a bug fix
- **GIVEN** a Jira ticket of type "Bug" describing a rendering issue
- **WHEN** the command generates the OpenSpec change
- **THEN** the change directory contains proposal.md, tasks.md, and at least one spec.md
  with ADDED or MODIFIED requirements and Gherkin scenarios
- **AND** `openspec validate` passes with --strict

#### Scenario: Spec generated for a multi-part feature
- **GIVEN** a Jira ticket of type "Story" requiring changes to multiple modules
- **WHEN** the command generates the OpenSpec change
- **THEN** tasks.md contains multiple implementation items
- **AND** spec.md contains multiple requirements with scenarios

---

### Requirement: Adaptive Issue Structure
The command SHALL assess ticket complexity and create an appropriate beads
issue structure. The agent decides autonomously:
- Simple work (bug fix, single-file) -> single beads issue
- Multi-part work (multiple modules, sequencing needed) -> epic with children

Each beads issue SHALL be linked to the Jira ticket via `--external-ref "jira:<key>"`.

#### Scenario: Simple bug creates single issue
- **GIVEN** a bug ticket affecting one component
- **WHEN** the agent assesses complexity
- **THEN** a single beads issue is created with external-ref to Jira

#### Scenario: Feature creates epic with children
- **GIVEN** a story ticket requiring frontend + backend changes
- **WHEN** the agent assesses complexity
- **THEN** an epic beads issue is created with child issues for each logical unit
- **AND** each child maps to a task in tasks.md

---

### Requirement: Plan Review Gate
The command SHALL spawn a fresh sub-agent (Task tool, subagent_type: "code-reviewer")
to review the spec and plan BEFORE presenting to the human. The sub-agent reviews for:
- Completeness (all acceptance criteria covered by scenarios)
- Feasibility (plan matches codebase capabilities)
- Missed edge cases
- Scope creep beyond the ticket

The primary agent SHALL incorporate feedback and regenerate spec if needed.

#### Scenario: Sub-agent catches missing scenario
- **GIVEN** a spec that covers happy path but misses an error case from the ticket
- **WHEN** the plan review sub-agent runs
- **THEN** it identifies the gap
- **AND** the primary agent adds the missing scenario before presenting to human

#### Scenario: Sub-agent confirms complete plan
- **GIVEN** a spec and plan that fully cover the ticket
- **WHEN** the plan review sub-agent runs
- **THEN** it confirms the plan is complete
- **AND** the primary agent presents to human noting "plan review: no issues found"

---

### Requirement: Human Checkpoint
The command SHALL present the reviewed plan to the human and require explicit
approval before starting implementation. The human can:
- **Approve** -- proceed to implementation
- **Adjust** -- provide feedback, which triggers re-review
- **Abort** -- clean up branch and beads issues, stop

With `--dry-run`, the command stops after presenting the plan.

#### Scenario: Human approves plan
- **GIVEN** the reviewed plan is presented
- **WHEN** the human selects "Approve"
- **THEN** the command proceeds to implementation

#### Scenario: Human requests adjustment
- **GIVEN** the reviewed plan is presented
- **WHEN** the human selects "Adjust" and provides feedback
- **THEN** the command incorporates feedback, re-runs plan review, re-presents

#### Scenario: Human aborts
- **GIVEN** the reviewed plan is presented
- **WHEN** the human selects "Abort"
- **THEN** the branch is deleted, beads issues are cleaned up, command stops

#### Scenario: Dry run
- **GIVEN** the --dry-run flag is set
- **WHEN** the reviewed plan is presented
- **THEN** the command stops without asking for approval

---

### Requirement: Isolated Implementation per Issue
The command SHALL implement each beads issue by spawning a fresh sub-agent
(Task tool, subagent_type: "general-purpose") with an isolated context containing:
- The target repo's CLAUDE.md and AGENTS.md
- The OpenSpec change files (proposal.md, spec.md, tasks.md)
- The specific beads issue to implement

Each sub-agent decides autonomously whether to use Plan mode, how to explore
the codebase, and what tests to write. Issues are executed sequentially
(children may depend on earlier siblings).

#### Scenario: Single issue implemented
- **GIVEN** a single beads issue for a bug fix
- **WHEN** the implementation phase runs
- **THEN** one sub-agent is spawned with the issue context
- **AND** it implements the fix, writes tests, and creates a checkpoint commit

#### Scenario: Multiple children implemented sequentially
- **GIVEN** an epic with 3 child issues
- **WHEN** the implementation phase runs
- **THEN** 3 sub-agents are spawned sequentially
- **AND** each receives the current repo state (including prior siblings' commits)
- **AND** each creates a checkpoint commit

---

### Requirement: Test Verification
The command SHALL run the target repo's test suite after implementation completes.
Test commands are detected from the repo's CLAUDE.md. If tests fail, the command
analyzes and fixes up to 3 times before stopping.

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

---

### Requirement: Implementation Review Gate
The command SHALL spawn a fresh sub-agent (Task tool, subagent_type: "code-reviewer")
to review the implementation against the spec. Reviews for:
- Spec compliance (code implements what spec says)
- Missing test coverage for Gherkin scenarios
- Logic errors, security issues, hardcoded values
- Over-engineering or scope creep
- Debug artifacts

If issues are found, the primary agent applies fixes and re-verifies (one cycle max).

#### Scenario: Review finds no issues
- **GIVEN** implementation matches the spec
- **WHEN** the implementation review sub-agent runs
- **THEN** it confirms compliance and the command proceeds

#### Scenario: Review finds fixable issues
- **GIVEN** implementation has a console.log left in and a missing test
- **WHEN** the implementation review sub-agent runs
- **THEN** it reports the issues
- **AND** the primary agent removes the console.log, adds the test, re-verifies

---

### Requirement: Local Dev Verification
The command SHALL start the target repo's local development server (detected
from CLAUDE.md, e.g., `./start-local.sh`) and tell the human what URL to visit
and what to look at to evaluate the working product.

#### Scenario: Local dev starts successfully
- **GIVEN** all tests pass and implementation review is clean
- **WHEN** the command starts local dev
- **THEN** it tells the human the app is running and what to evaluate

---

### Requirement: PR Creation
The command SHALL push the branch and create a GitHub PR via `gh pr create` with:
- Title: `<jira-key>: <ticket-summary>`
- Body: Jira link, spec summary, changes list, test plan
- Footer: "Automated by /dark-factory"

The command SHALL close all beads issues with the PR URL as reason.

#### Scenario: PR created successfully
- **GIVEN** local dev verification is complete
- **WHEN** the command creates the PR
- **THEN** the PR title contains the Jira key
- **AND** the PR body links to the Jira ticket
- **AND** all beads issues are closed with the PR URL

---

### Requirement: Error Handling and Cleanup
The command SHALL stop and report on any phase failure. On abort or fatal error,
the command cleans up: deletes the branch (if created), removes beads issues
(if created).

#### Scenario: Phase failure stops execution
- **GIVEN** the Jira ticket cannot be fetched (network error, invalid key)
- **WHEN** Phase 1 fails
- **THEN** the command stops, reports the error, and does not proceed

#### Scenario: Abort cleans up
- **GIVEN** the user aborts at the human checkpoint
- **WHEN** cleanup runs
- **THEN** the feature branch is deleted and beads issues are removed
