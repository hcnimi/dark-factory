Autonomous spec-to-PR pipeline: $ARGUMENTS

Delegates all orchestration to the `dark_factory` Python package.

## Quick Start

```bash
dark-factory run $ARGUMENTS
```

Read the JSON output. If `status` is `"error"`, stop and report.

## What the Pipeline Does

The `dark-factory run` command handles the full pipeline:

1. **Intent Clarification** -- Parse the source (Jira key, file, or inline description) and produce a structured intent document with title, summary, and acceptance criteria.
2. **Implementation** -- Create a worktree, implement changes using Claude Agent SDK, and commit.
3. **Evaluation** -- Score the implementation against the intent (correctness, completeness, code quality).

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Stop after intent clarification (no implementation or evaluation) |
| `--gate-intent` | Pause for human approval after intent, before implementing |
| `--gate-eval` | Pause for human approval after evaluation |
| `--in-place` | Work in repo directly instead of a git worktree |
| `--max-cost N` | Cap total cost at N USD (default: 10) |
| `--evaluator-model M` | Model for evaluation (default: claude-sonnet-4-20250514) |

## Standalone Evaluation

To evaluate an existing branch without re-running the pipeline:

```bash
dark-factory evaluate <branch> [--intent <path>] [--evaluator-model <model>]
```

## Rules

- If any phase fails, stop and report
- Never skip the human checkpoint when `--gate-intent` is set
- Max cost guard prevents runaway spending
- Diff-size is reported in evaluation output

## Usage

```
/dark-factory <jira-key|file|description> [--dry-run] [--gate-intent] [--in-place]
```
