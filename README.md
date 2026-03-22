# Dark Factory

> **A note on the name:** "Dark factory" evokes fully lights-out autonomous manufacturing — and while the pipeline does automate the path from ticket to pull request, it is not a push-button replacement for human engineering judgment. A human checkpoint gate (Phase 5) is mandatory, every PR still requires human review, and the pipeline does not extend into CI/CD, deployment, or post-merge automation. Treat this as a **developer-acceleration tool** that drafts PRs, not an autonomous production system. The long-term aspiration is fully lights-out operation — but we're not there yet.

Deterministic Python pipeline for spec-to-PR orchestration. Takes a Jira ticket, spec file, or inline description and produces a ready-to-review pull request — calling LLMs only when intelligence is required, keeping everything else in code-controlled deterministic phases.

## Install

```bash
# Python package (editable)
pip install -e .

# Claude Code plugin: clone this repo, then install as a plugin
```

## Usage

As a Claude Code slash command:

```bash
# From a Jira ticket
/dark-factory PROJECT-123

# From a spec file
/dark-factory specs/feature.md

# From an inline description
/dark-factory "add dark mode toggle to settings page"

# Options
/dark-factory PROJECT-123 --dry-run    # Plan without executing
/dark-factory PROJECT-123 --resume     # Resume from last failure
```

Direct CLI:

```bash
python3 -m dark_factory run <source> [--dry-run] [--resume]
```

## Phase Pipeline

The pipeline executes 12 phases in sequence. Deterministic phases consume zero LLM tokens.

| Phase | Name | Type | What It Does |
|-------|------|------|--------------|
| 0 | Tool Discovery | Deterministic | Parse args, check tools (`git`, `gh`), init state |
| 1 | Source Ingestion | Deterministic | Extract structured fields from Jira/file/inline |
| 1.5 | Input Quality Gate | SDK (Sonnet) | DoR + INVEST assessment, blocks bad input early |
| 2 | Codebase Exploration | Mixed | Deterministic context pre-fetch (2a) + SDK exploration (2b) |
| 3 | Scaffold & OpenSpec | SDK (Opus) | Branch/worktree creation, dependency install, spec generation |
| 4 | Plan Review Gate | SDK (Sonnet) | Review plan for completeness and feasibility |
| 5 | Human Checkpoint | Deterministic | Render plan summary, capture approve/modify/abort decision |
| 6 | Issue Creation | Deterministic | Create beads issues from tasks, parse dependency DAG |
| 6.5 | Test Generation | SDK (Sonnet) | Generate visible (TDD) + holdout (validation) test sets |
| 7 | Implementation | SDK (Opus) | Implement issues — sequential or parallel waves |
| 8 | Verification | SDK (Opus) | Run tests, dependency audit, holdout test execution |
| 9 | Review | SDK (Sonnet/Opus) | Diff review + fix cycle (max 1 cycle) |
| 10 | Dev Verification | Deterministic | Detect dev server, render verification checklist |
| 11 | PR Creation | SDK (Sonnet) | Push branch, generate PR body, create PR via `gh` |

Sub-phase routing is automatic: 1→1.5→2, 6→6.5→7.

## Architecture

```
dark_factory/
├── __main__.py          # Entry point, phase dispatch, full pipeline run
├── __init__.py          # Package metadata (v0.1.0)
├── cli.py               # Argument parsing, source classification (Phase 0)
├── state.py             # PipelineState persistence, SourceInfo
├── orchestrator.py      # CompletionSummary, diff-size guard, event logging
├── ingest.py            # TicketFields extraction from Jira/file/inline
├── explore.py           # ContextBundle, Phase 2 exploration
├── context_engineering.py  # Import graph, test-source mapping, symbol extraction
├── scaffold.py          # Phase 3-4: branch, worktree, spec generation, plan review
├── checkpoint.py        # Phase 5: plan summary rendering, decision parsing
├── issues.py            # Phase 6: TaskDAG, dependency parsing, wave resolution
├── pipeline.py          # Phase execution: 1.5, 6.5, 7, 9
├── verify.py            # Phase 8/10: test runner, dependency audit, dev verification
├── pr.py                # Phase 11: push, PR body generation, PR creation
├── agents.py            # SDK call wrappers with model/tool/turn configuration
├── security.py          # SecurityPolicy enforcement on every tool invocation
└── worktree.py          # Parallel worktree creation and cleanup
```

### Data Flow

```
Input (Jira/file/inline)
  → SourceInfo (kind, raw, id)
    → TicketFields (summary, description, AC, labels, constraints)
      → Quality Gate (DoR/INVEST scoring)
        → ContextBundle (repo structure, imports, symbols, test mapping)
          → OpenSpec scaffold (design, specs, tasks)
            → Human checkpoint (approve/modify/abort)
              → Beads issues + TaskDAG (dependency waves)
                → Test generation (visible + holdout split)
                  → Implementation (parallel waves of SDK agents)
                    → Verification (tests, audit, review)
                      → Pull Request
```

### LLM Agent Configuration

| Agent | Model | Max Turns | Tools | Used In |
|-------|-------|-----------|-------|---------|
| Implement | Opus | 30 | Read, Edit, Write, Bash, Glob, Grep | Phase 7 |
| Fix | Opus | 15 | Edit tools | Phase 8 |
| Review | Sonnet | 10 | Read, Glob, Grep (read-only) | Phase 9 |
| PR Body | Sonnet | 3 | None | Phase 11 |
| Quality Gate | Sonnet | 3 | None | Phase 1.5 |
| Test Gen | Sonnet | 10 | Read tools | Phase 6.5 |

## Key Features

### TDD + Holdout Tests (Phase 6.5)

Tests are generated from the spec *before* implementation by a separate agent, split into two sets:

- **Visible tests** — given to the implementing agent as TDD targets
- **Holdout tests** — hidden from the implementer, used as independent validation in Phase 8

This adversarial decomposition prevents the implementing agent from writing tests that share its own misunderstandings.

### Parallel Task Execution (Phase 7)

Tasks can declare dependencies using markers (`[P]` for parallel-safe, `[depends: N,M]`). The `TaskDAG` resolves these into execution waves:

```
Wave 1: [independent tasks] → run concurrently (max 3)
Wave 2: [tasks depending on Wave 1] → run after Wave 1 completes
```

Each parallel task gets its own git worktree. Merge conflicts are detected and reported (task marked `needs-manual-merge`).

### Context Engineering (Phase 2a)

Three deterministic layers reduce LLM exploration burden:

1. **Import graph** — language-aware (Python, TypeScript, Go) dependency tracing with 2-hop neighborhood
2. **Test-source mapping** — convention-based discovery of which tests cover which source files
3. **Symbol extraction** — function/class/type signatures without bodies (the "API surface" view)

### Security Policy

Code-level enforcement on every tool invocation:

- Blocked patterns: `rm -rf /`, `git push --force`, `git reset --hard`, etc.
- Write boundary: file writes restricted to worktree path
- Blocked tools: Excalidraw MCP tools

### State & Resumability

Pipeline state persists to `.dark-factory/<source_id>.json`. Use `--resume` to continue from the last successful phase after a failure. Events are logged to `.dark-factory/<source_id>.events.jsonl` in JSONL format.

### Feedback Loops

- **Lint-in-loop**: implementing agents run linting after each file change
- **Self-review checklist**: structured self-check at end of implementation (diff stat, debug artifacts, test coverage)
- **Targeted tests between tasks**: run relevant tests after each issue, not just at the end

### Diff-Size Guard

Warns if the total diff exceeds 3x the expected size per task, catching over-engineering before PR creation.

## Individual Phase Access

For debugging or targeted re-runs of deterministic phases:

```bash
python3 -m dark_factory 0 <source>         # Phase 0: parse + validate
echo '<json>' | python3 -m dark_factory 5  # Phase 5: checkpoint prompt
echo '<json>' | python3 -m dark_factory 6  # Phase 6: issue creation
echo '<json>' | python3 -m dark_factory 10 # Phase 10: verification checklist
```

## Rules

- Never skip the human checkpoint (Phase 5)
- One sub-agent per beads issue in Phase 7
- Max 2 test-fix retries in Phase 8
- Max 1 review-fix cycle in Phase 9
- Off-rails detection interrupts stuck agents (repeated messages or >100 turns)
- Completion summary prints per-phase timing, cost, and turns

## Dependencies

- **Required tools**: `git`, `gh`
- **Optional tools**: `jira` (for Jira input), `bd` (beads issue tracking), `npm`/`pytest`/`make`/`cargo`/`go` (detected per project)
- **Python**: Claude Agent SDK for LLM calls

## Related

The Claude Code-orchestrated variant (`/dark-factory-cc`) remains in [ai-dev](https://github.com/hcnimi/ai-dev). It provides the same pipeline but with Claude Code as the orchestrator instead of Python.
