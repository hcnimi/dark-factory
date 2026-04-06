Autonomous spec-to-PR pipeline: $ARGUMENTS

Delegates all orchestration to the `dark_factory` Python package.

## What the Pipeline Does

1. **Intent Clarification** -- Parse the source and produce a structured intent document.
2. **Implementation** -- Create a worktree, implement changes using Claude Agent SDK, and commit.
3. **Evaluation** -- Score the implementation against the intent.

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Stop after intent clarification (no implementation or evaluation) |
| `--gate-intent` | Pause for human approval after intent, before implementing |
| `--gate-eval` | Pause for human approval after evaluation |
| `--in-place` | Work in repo directly instead of a git worktree |
| `--max-cost N` | Cap total cost at N USD (default: 10) |
| `--evaluator-model M` | Model for evaluation (default: claude-sonnet-4-20250514) |

## Execution

Run the pipeline. Gates cause the process to exit with code 75 -- this is expected, not an error.

### Step 1: Initial run

```bash
dark-factory run $ARGUMENTS 2>&1
```

Save the full output and note the exit code.

### Step 2: Check result

- **Exit 0**: Success. The last lines of output contain a JSON summary. Report the result to the user.
- **Exit 75 (gate)**: This is a gate pause, not an error. Go to Step 3.
- **Any other exit code**: Failure. Report the error output to the user. Stop.

### Step 3: Handle gate

When exit code is 75, the **last line** of stdout is a JSON object with a `__gate__` key. Parse it to get `run_id` and `state_file`.

Read the state file (JSON) to get details:

- For `"__gate__": "intent"`: extract the `.intent` field and display the title, summary, and acceptance criteria to the user. Ask: **"Approve this intent and proceed to implementation, or abort?"**
- For `"__gate__": "eval"`: read the evaluation file at `.dark-factory/<run_id>.evaluation.json` and display the scores and criteria results. Ask: **"Accept this evaluation and complete the run, or abort?"**

### Step 4: Resume or abort

- **If the user approves**: Run `dark-factory run --resume <run_id> 2>&1`. Go back to Step 2 (the resumed run may hit another gate).
- **If the user rejects**: Report that the run was aborted. Stop.

## Standalone Evaluation

```bash
dark-factory evaluate <branch> [--intent <path>] [--evaluator-model <model>]
```

## Rules

- If any phase fails, stop and report
- Never skip the human checkpoint when a gate flag is set
- Max cost guard prevents runaway spending
- Exit code 75 means "paused at gate" -- always handle it, never treat as error

## Usage

```
/dark-factory <jira-key|file|description> [--dry-run] [--gate-intent] [--gate-eval] [--in-place]
```
