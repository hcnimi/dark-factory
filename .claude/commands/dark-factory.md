Autonomous Jira-to-PR pipeline: $ARGUMENTS

You orchestrate the full development loop from a Jira ticket to a tested PR.
Phases 0-5 (spec creation and review) run here in the skill layer using MCP
and Claude Code tools. Phases 6-11 (implementation) are delegated to the
dark-factory Python pipeline via `--from-spec`.

## Usage

```
/dark-factory <jira-key> [--dry-run] [--resume]
```

## Parameters

- `jira-key`: A Jira ticket key (e.g., `SDLC-123`, `PORTAL-456`)
- `--dry-run`: Stop after presenting the reviewed plan (Phase 5) — do not implement
- `--resume`: Force resume of existing session (skip fresh-start prompt)

## Rules

- **If any phase fails, stop and report.** Do not proceed to subsequent phases.
- **Never skip the human checkpoint.** The plan must be approved before implementation.
- **Worktree isolation.** All implementation work happens in a git worktree.
- **Max 2 test-fix retries** in the pipeline's Phase 8.
- **Max 1 review-fix cycle** in the pipeline's Phase 9.

## Bash Command Discipline

Claude Code's permission system matches the **first token** of each Bash command.
To avoid approval prompts during autonomous execution:

1. **No variable assignments as Bash calls.** Instead of `VAR=$(cmd)`, run `cmd`
   directly and use the output in your next step.
2. **One command per Bash call.** Instead of `[ -f file ] && cmd`, check with
   `test -f file` first, then run `cmd` separately.
3. **Use `git -C <dir>` instead of `cd <dir> && git ...`** for git ops.
4. **Pre-approved first tokens**: git, gh, bd, openspec, npm, yarn, pnpm, pytest,
   python3, make, cargo, go, docker, command, which, ls, find, grep, echo, cat,
   head, tail, wc, mkdir, rm -f, rmdir, basename, dirname, tr, sed, sort, jq,
   test, timeout, tee, touch, diff.

## Process

### Phase 0: Setup

1. Locate required tools (run each as a separate Bash call):
   ```bash
   command -v bd
   ```
   ```bash
   command -v gh
   ```
   ```bash
   command -v openspec
   ```
   If any is missing, stop and tell the user what to install.

2. Verify GitHub auth:
   ```bash
   gh auth status
   ```
   If not authenticated, tell user to run `gh auth login`.

3. Parse `$ARGUMENTS` for the Jira key and flags (`--dry-run`, `--resume`).
   Validate the key format matches `[A-Z]+-\d+`. If not, stop with:
   "Invalid Jira key format. Expected something like SDLC-123."

4. Discover Atlassian cloud ID:
   ```
   mcp__claude_ai_Atlassian__getAccessibleAtlassianResources()
   ```
   Use the first available cloud ID. If none found, stop with:
   "No Atlassian sites found. Ensure the Atlassian MCP is connected."

5. Session detection — check for prior dark-factory run:
   a. Check if progress file `.dark-factory/<JIRA-KEY>.md` exists in the repo root.
   b. Check if branch `dark-factory/<jira-key-lowercase>` exists (local or remote):
      `git branch --list "dark-factory/<jira-key-lowercase>"`
      `git branch -r --list "origin/dark-factory/<jira-key-lowercase>"`
   c. Determine resume point:
      - **Progress file exists** -> read current phase and worktree path from it.
        Validate worktree still exists: `git worktree list --porcelain`
        If worktree missing but branch exists: `git worktree prune` then recreate.
      - **No progress file but branch exists** -> recreate worktree, resume at Phase 4.
      - **Neither found** -> fresh start, proceed to Phase 1.
   d. Present Resume Checkpoint (via AskUserQuestion):
      ```
      DARK FACTORY -- Session Resume

      Ticket: <jira-key>
      Branch: dark-factory/<jira-key-lowercase>
      Last phase: <N> (<phase-name>)

      (A) Resume from Phase <N>
      (B) Restart fresh (removes worktree and branch)
      (C) Abort
      ```
   e. Handle response:
      - **Resume**: skip to detected phase
      - **Restart**: remove worktree + branch, proceed as fresh start
      - **Abort**: clean up, stop
      - **`--resume` flag**: skip prompt, go directly to Resume

### Phase 1: Jira Ticket Ingestion

6. Fetch the ticket via MCP:
   ```
   mcp__claude_ai_Atlassian__getJiraIssue(
     cloudId="<cloud-id>",
     issueIdOrKey="<jira-key>",
     responseContentFormat="markdown"
   )
   ```

7. Extract from the response:
   - `<summary>`: issue title / summary field
   - `<description>`: issue description (markdown)
   - `<acceptance-criteria>`: from description (look for "Acceptance Criteria"
     heading or checklist items) or custom fields
   - `<issue-type>`: Bug, Story, Task, etc.
   - `<priority>`: Critical, High, Medium, Low

### Phase 1.5: Sufficiency Check

8. If `<description>` is empty or under 50 characters with no acceptance criteria,
   stop with:
   ```
   Ticket <jira-key> lacks sufficient detail to proceed.
   Please add a description with acceptance criteria and re-run.
   ```

9. Present a brief summary:
   ```
   Ticket: <jira-key> -- <summary>
   Type: <issue-type> | Priority: <priority>
   Acceptance criteria: <count> items
   ```

### Phase 2: Codebase Exploration

> **Note**: Exploration runs in the main repo working directory. The worktree
> has not been created yet.

10. Get the repo root:
    ```bash
    git rev-parse --show-toplevel
    ```

11. Read the target repo's `CLAUDE.md` (if it exists) for project conventions,
    test commands, and local dev setup.

12. Deterministic pre-fetch:
    - List top-level project structure (use Glob and LS)
    - Identify package boundaries (package.json, pyproject.toml, go.mod, etc.)
    - Recent commits: `git log --oneline -10`

13. Explore the codebase based on the ticket content:
    - Search for files, modules, and patterns relevant to the ticket (Glob, Grep)
    - Read existing tests to understand testing conventions
    - Identify the scope of changes needed

14. Note key findings: relevant files, existing patterns, test framework,
    integration strategy.

### Phase 3: Feature Branch, Worktree, and OpenSpec Generation

15. Derive identifiers:
    - `<jira-key-lowercase>`: lowercase Jira key (e.g., `sdlc-123`)
    - `<change-id>`: `dark-factory-<jira-key-lowercase>`

16. Create the feature branch and worktree (run each as a separate Bash call):
    ```bash
    git rev-parse --show-toplevel
    ```
    ```bash
    basename "<repo-root>"
    ```
    Compute worktree path: `<repo-root>/../<basename>-df-<jira-key-lowercase>`
    ```bash
    git worktree add -b "dark-factory/<jira-key-lowercase>" "<worktree-path>" main
    ```

17. Install dependencies in the worktree if applicable:
    ```bash
    ls "<worktree-path>/yarn.lock" "<worktree-path>/package-lock.json" "<worktree-path>/pnpm-lock.yaml" 2>/dev/null
    ```
    Then run the appropriate install command (yarn/npm/pnpm).

18. Ensure `.dark-factory/` is gitignored in the main repo:
    ```bash
    grep -q "^\.dark-factory" "<repo-root>/.gitignore" 2>/dev/null || echo ".dark-factory/" >> "<repo-root>/.gitignore"
    ```

19. Create the progress file `<repo-root>/.dark-factory/<JIRA-KEY>.md`:
    ```markdown
    # Dark Factory Session -- <JIRA-KEY>

    ## Session Info
    - **Jira**: <JIRA-KEY>
    - **Branch**: dark-factory/<jira-key-lowercase>
    - **Worktree**: <absolute-worktree-path>
    - **Repo**: <absolute-main-repo-path>
    - **Started**: <ISO-8601 timestamp>
    - **Current Phase**: 3

    ## Completed Phases
    - [x] Phase 0: Setup
    - [x] Phase 1: Jira Ticket Ingestion
    - [x] Phase 2: Codebase Exploration
    - [ ] Phase 3: OpenSpec Generation
    - [ ] Phase 4: Plan Review Gate
    - [ ] Phase 5: Human Checkpoint
    - [ ] Phase 6-11: Implementation (pipeline)
    ```

20. Create the OpenSpec change directory in the worktree:
    ```bash
    mkdir -p "<worktree-path>/openspec/changes/<change-id>/specs/main"
    ```

21. Generate the change files using the Write tool:

    **`proposal.md`** in `openspec/changes/<change-id>/`:
    ```markdown
    # <summary>

    ## Why
    <from ticket description -- the problem being solved>

    ## What Changes
    <high-level description derived from exploration findings>

    ## Impact
    - Jira: <jira-key>
    - Affected files: <list from exploration>
    ```

    **`specs/main/spec.md`** in `openspec/changes/<change-id>/`:
    Requirements in OpenSpec delta format with Gherkin scenarios. Each acceptance
    criterion from the ticket becomes a requirement with GIVEN/WHEN/THEN.

    For API endpoints, add scenarios for: upstream unavailable, error status,
    invalid input. For UI views, add: loading, error, empty states.

    **`tasks.md`** in `openspec/changes/<change-id>/`:
    Ordered implementation checklist. Each task maps to a beads issue.
    Tasks marked `[P]` can run in parallel. Unmarked tasks are sequential.
    Constraint: `[P]` tasks must NOT modify the same files.

22. Validate the change:
    ```bash
    openspec validate <change-id> --strict
    ```
    If validation fails, fix and retry (up to 2 attempts).

### Phase 4: Plan Review Gate

23. Spawn a review sub-agent:
    ```
    Agent(
      subagent_type: "code-reviewer",
      prompt: "Review the following development plan for completeness,
               feasibility, missed edge cases, and scope creep.

               ## Jira Ticket
               <ticket summary and acceptance criteria>

               ## OpenSpec Change
               <contents of proposal.md, spec.md, and tasks.md>

               ## Codebase Context
               <key findings from exploration>

               Review criteria:
               1. Are ALL acceptance criteria covered by Gherkin scenarios?
               2. Is the plan feasible given the codebase structure?
               3. Are there edge cases the spec missed?
               4. Does the plan stay within the ticket's scope?

               Return: issues (if any), suggestions, and verdict (PASS / NEEDS_WORK)."
    )
    ```

24. If NEEDS_WORK: incorporate feedback, re-validate with openspec, proceed.

25. Commit the OpenSpec change files in the worktree:
    ```bash
    git -C "<worktree-path>" add openspec/changes/<change-id>/
    ```
    ```bash
    git -C "<worktree-path>" commit -m "checkpoint(openspec): add spec for <jira-key>"
    ```

26. Update the progress file: mark Phase 4 completed.

### Phase 5: Human Checkpoint

27. Present the reviewed plan using AskUserQuestion:
    ```
    ========================================
    DARK FACTORY -- Plan Review
    ========================================

    Ticket: <jira-key> -- <summary>
    Branch: dark-factory/<jira-key-lowercase>
    Worktree: <worktree-path>
    Plan review: <PASS or "issues addressed: <list>">

    ## Spec Summary
    <1-2 sentence overview>

    ## Requirements (<count>)
    <bulleted list of requirement names from spec.md>

    ## Implementation Plan (<count> tasks)
    <numbered task list from tasks.md>

    ========================================

    (A) Approve -- proceed to implementation
    (B) Adjust -- provide feedback (will re-review)
    (C) Abort -- clean up and stop
    ```

28. Handle the response:
    - **Approve**: proceed to pipeline handoff
    - **Adjust**: incorporate feedback, re-run Phase 4, re-present
    - **Abort**: run Cleanup Protocol, stop
    - **`--dry-run`**: present plan, then stop with "Dry run complete."

### Phases 6-11: Implementation (Pipeline Handoff)

29. Hand off to the dark-factory pipeline for implementation:
    ```bash
    dark-factory run --from-spec "<worktree-path>/openspec/changes/<change-id>"
    ```
    The pipeline handles: issue creation, test generation, implementation,
    test verification, review, and PR creation.

30. Read the pipeline's JSON output. If `status` is `"error"`, report the
    failure. If `status` is `"success"`, report completion:
    ```
    ========================================
    DARK FACTORY -- Complete
    ========================================

    Ticket: <jira-key> -- <summary>
    PR: <pr-url>
    Branch: dark-factory/<jira-key-lowercase>

    Next: review the PR, request reviews, merge.
    ========================================
    ```

## Error Recovery

| Phase | Failure | Action |
|-------|---------|--------|
| 0 | Missing tool | Stop, tell user what to install |
| 0 | No Atlassian MCP | Stop, tell user to connect MCP |
| 0 | Prior session | Present Resume Checkpoint |
| 1 | Fetch error | Stop, report error |
| 1.5 | Insufficient detail | Stop, ask user to update ticket |
| 3 | OpenSpec validation fails | Fix and retry (2x), then warn |
| 4 | Review sub-agent fails | Proceed without review |
| 5 | Human aborts | Run Cleanup Protocol |
| 6-11 | Pipeline fails | Report pipeline error output |

## Cleanup Protocol

When aborting or on unrecoverable error:
```bash
rm -f "<repo-root>/.dark-factory/<JIRA-KEY>.md"
rmdir "<repo-root>/.dark-factory" 2>/dev/null
git -C "<repo-root>" worktree remove "<worktree-path>" --force 2>/dev/null
git branch -D "dark-factory/<jira-key-lowercase>" 2>/dev/null
```

## Examples

```
/dark-factory SDLC-123
/dark-factory PORTAL-456 --dry-run
/dark-factory SDLC-123 --resume
```
