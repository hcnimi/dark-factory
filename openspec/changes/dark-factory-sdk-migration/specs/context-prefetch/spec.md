## ADDED Requirements

### Requirement: Deterministic pre-fetch collects baseline context
Phase 2a SHALL run as a Python function (no LLM) that collects a structured context bundle from the target repository. The bundle MUST include: repo structure, project metadata, CI/CD configuration, test infrastructure, and convention files.

#### Scenario: Repo structure collected
- **WHEN** Phase 2a runs against a repository
- **THEN** the context bundle contains the top-level directory listing and root-level documentation files (*.md, maxdepth 2)

#### Scenario: Project metadata extracted
- **WHEN** the repository contains `package.json`, `pyproject.toml`, or `go.mod`
- **THEN** the context bundle contains parsed metadata including project name, scripts/commands, and dependency names

#### Scenario: CI configuration always inspected
- **WHEN** Phase 2a runs against a repository
- **THEN** the context bundle contains contents of CI files (`blackbird.yaml`, `buildspec.yml`, `.github/workflows/*.yml`, `Dockerfile`) if they exist — regardless of LLM exploration decisions

#### Scenario: Test infrastructure detected
- **WHEN** the repository contains test configuration files (`jest.config*`, `pytest.ini`, `conftest.py`, `vitest.config*`)
- **THEN** the context bundle contains their paths and the test/lint commands extracted from project metadata scripts

#### Scenario: Convention files included
- **WHEN** the repository contains `CLAUDE.md`, `AGENTS.md`, or `.cursorrules`
- **THEN** the context bundle contains their full contents for injection into subsequent agent prompts

### Requirement: Pre-fetch includes recent git history
Phase 2a SHALL collect recent git activity to provide pattern context to the exploration agent.

#### Scenario: Recent commits collected
- **WHEN** Phase 2a runs
- **THEN** the context bundle contains the 20 most recent commit messages (oneline format) and recently added files from the last 10 commits

### Requirement: Keyword-based code search from ticket
Phase 2a SHALL extract identifiers from the ticket summary and acceptance criteria and search for matching files in the repository.

#### Scenario: Ticket keywords searched
- **WHEN** the ingested ticket contains identifiable nouns/identifiers in summary or acceptance criteria
- **THEN** the context bundle contains file paths matching those keywords (up to 20 results) from `grep -rl` against the source directory

### Requirement: Pre-fetched context passed to exploration agent
Phase 2b (LLM exploration) SHALL receive the Phase 2a context bundle as input. The exploration agent's scope SHALL be reduced to gaps not covered by deterministic pre-fetch.

#### Scenario: Exploration receives bundle
- **WHEN** Phase 2b SDK call is made
- **THEN** the system prompt includes the full context bundle, and the agent prompt instructs it to explore architecture, module boundaries, and patterns NOT already captured in the bundle

#### Scenario: Exploration does not repeat pre-fetch work
- **WHEN** the exploration agent runs with the context bundle
- **THEN** it does not re-read files already included in the bundle (CI config, convention files, project metadata)
