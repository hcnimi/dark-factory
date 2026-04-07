Autonomous spec-to-PR pipeline: $ARGUMENTS

Delegates orchestration to the `dark_factory` Python package in phased steps. Each Bash call completes quickly; the long-running implementation uses the Agent tool.

## What the Pipeline Does

1. **Intent Clarification** — Parse the source and produce a structured intent document.
2. **Prepare** — Create worktree and write prompt files.
3. **Implementation** — Agent tool implements changes (no Bash timeout).
4. **Verify** — Run tests and capture diff.
5. **Evaluation** — Score the implementation against the intent.

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Stop after intent clarification (no implementation or evaluation) |
| `--gate-eval` | Pause for human approval after evaluation |
| `--in-place` | Work in repo directly instead of a git worktree |
| `--max-cost N` | Cap total cost at N USD (default: 10) |
| `--evaluator-model M` | Model for evaluation (default: claude-opus-4-6) |
| `--analyze-spec` | Quality-check the intent before implementation |
| `--no-assess` | Skip automatic input assessment |

## Execution

### Step 1: Intent clarification

Always inject `--gate-intent`. Pass through all user flags including `--dry-run`.

```bash
dark-factory run $ARGUMENTS --gate-intent 2>&1
```

Save the full output and note the exit code.

### Step 2: Check exit code

- **Exit 0**: Pipeline completed (only happens with `--dry-run` since `--gate-intent` is set). Report the intent and stop.
- **Exit 75 (gate)**: Parse the gate JSON from the last stdout line. Proceed to Step 3.
- **Any other exit code**: Failure. Report the error output to the user. Stop.

### Step 3: Present intent to user

Read the state file (from the gate JSON `state_file` field) to get the `.intent` field. Display the title, summary, and acceptance criteria.

If the gate JSON contains a `clarifications` array, present each question to the user and ask if they want to answer them to improve the implementation. If yes: collect answers, write them to the state file's `.interview` field, and note the answers when approving.

If `.spec_analysis` is present in state, display the scores and suggestions.

If the user included `--dry-run`: present the intent and **stop** (do not proceed to implementation).

Otherwise, ask: **"Approve this intent and proceed to implementation, or abort?"**

If rejected: stop.

### Step 4: Prepare workspace

```bash
dark-factory prepare <run-id> 2>&1
```

Parse the JSON output to get `work_dir`, `prompt_file`, and `system_prompt_file`.

### Step 5: Read prompt files

Read both `prompt_file` and `system_prompt_file` from the paths in Step 4's JSON output.

### Step 6: Implementation via Agent tool

Launch an Agent tool with:
- The system prompt content as context
- The user prompt content as the task
- `cwd` set to `work_dir` from Step 4

This runs as long as needed with no Bash timeout.

### Step 7: Verify

```bash
dark-factory verify <run-id> 2>&1
```

Parse the JSON output. Check `tests_passed`.

### Step 8: Fix loop (if tests failed)

If `tests_passed` is false and this is the first retry:

1. Launch an Agent tool with the `test_output` from Step 7 as context, asking it to fix the failures. Use the same `work_dir`.
2. Go back to Step 7 (re-run verify).

Allow at most 2 retries. If tests still fail after retries, proceed to evaluation anyway.

### Step 9: Evaluation

```bash
dark-factory evaluate --run <run-id> 2>&1
```

If `--gate-eval` was in the user's flags, this may exit 75.

### Step 10: Handle evaluation gate (if exit 75)

Read the evaluation file at `.dark-factory/<run-id>.evaluation.json`. Display the scores and criteria. Ask: **"Accept this evaluation and complete the run, or abort?"**

If approved:
```bash
dark-factory complete <run-id> 2>&1
```

If rejected: stop.

### Step 11: Report completion

Report the final status including cost, scores, and branch name.

## Standalone Evaluation

```bash
dark-factory evaluate <branch> [--intent <path>] [--evaluator-model <model>]
```

## Rules

- If any phase fails, stop and report
- Never skip the human checkpoint when a gate flag is set
- `--gate-intent` is always injected — the slash command controls the gate
- Max cost guard prevents runaway spending
- Exit code 75 means "paused at gate" — always handle it, never treat as error

## Usage

```
/dark-factory <jira-key|file|description> [--dry-run] [--gate-eval] [--in-place]
```
