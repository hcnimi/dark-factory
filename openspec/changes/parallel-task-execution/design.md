## Context

Phase 7 currently iterates `for issue in issues:` sequentially, calling `call_implement()` for each. Each call gets up to 30 Opus turns in a shared worktree. The `parse_tasks_md()` function already recognizes `[P]` markers but nothing downstream uses them.

The pipeline is fully async. `call_implement()` is an async function that wraps `ClaudeSDKClient`. Git worktrees are used for isolation (Phase 7 already runs in a worktree). The test-to-source mapping from Priority 3 is available to inform file-conflict detection.

## Goals / Non-Goals

**Goals:**
- Run independent tasks concurrently via `asyncio.gather`, reducing wall-clock time
- Parse and respect dependency markers (`[P]`, `[depends: N]`) from Phase 3 output
- Detect and handle merge conflicts when parallel branches converge
- Fail gracefully: a broken parallel task doesn't poison unrelated tasks

**Non-Goals:**
- Branch-per-task with full PR workflow (Level 2) — future work
- Agent Teams / multi-model collaboration (Level 3) — future work
- Automatic independence classification — Phase 3's LLM must emit markers; we don't infer
- Cross-repo or multi-service parallel execution

## Decisions

### 1. Wave-based execution model

Group tasks into execution waves using topological sort of the dependency DAG.

```
Wave 0: [task-1 [P], task-3 [P]]     ← run concurrently
Wave 1: [task-2 [depends: 1]]         ← run after wave 0
Wave 2: [task-4 [depends: 2], task-5 [P]]  ← mixed: 4 waits for 2, 5 runs immediately
```

**Why over free-form scheduling**: Waves are simple to reason about, debug, and report progress on. A proper task scheduler (run each task the moment its deps clear) saves little wall-clock time in practice — most pipelines have 4-8 tasks with 1-2 dependency chains.

**Alternative considered**: Single-task-at-a-time with async queue. Rejected — adds complexity (locks, queue management) for marginal gain over wave batching.

### 2. Worktree-per-agent isolation

Each parallel agent in a wave gets its own git worktree branched from the current state. After the wave completes, branches are merged sequentially back into the main worktree.

```
main-worktree (at commit X)
  ├── worktree-task-1 (branch: parallel/task-1)
  └── worktree-task-3 (branch: parallel/task-3)

After wave 0:
  merge parallel/task-1 → main-worktree
  merge parallel/task-3 → main-worktree
```

**Why not shared worktree**: Two agents writing to the same files simultaneously causes data races. Even "independent" tasks might touch shared config files, lock files, or generated code.

**Why worktrees over clones**: Worktrees share the `.git` object store, so creation is near-instant (~100ms) and uses negligible disk. `git worktree add` is the standard tool for this.

**Alternative considered**: File-level locking in a shared worktree. Rejected — fragile, doesn't handle new files, and the merge step is needed anyway to detect unexpected conflicts.

### 3. Dependency marker format

Extend the existing `[P]` marker with `[depends: N]` where N is the 1-based task number:

```markdown
1. [P] Add user validation endpoint
2. [P] Add email notification service
3. [depends: 1, 2] Wire validation into notification flow
4. [P] Update API documentation
```

Tasks without any marker default to **sequential** (treated as `[depends: N-1]`), preserving backward compatibility with existing tasks.md files that have no markers.

**Why 1-based task numbers**: Matches the numbered list in tasks.md. The DAG builder maps these to issue IDs after Phase 6 creates them.

### 4. Merge conflict resolution strategy

After each wave, merge branches sequentially. If a merge conflict occurs:

1. Attempt auto-resolution (`git merge --no-edit`)
2. If conflict: abort the merge, mark the task as `needs-manual-merge`, continue with remaining merges
3. Report all conflicts at end of Phase 7 for human review

**Why not auto-resolve with LLM**: Merge conflicts in generated code are rare (the LLM classified tasks as independent). When they do occur, they signal a classification error — the human should review whether the tasks were truly independent.

### 5. Concurrency limit

Cap parallel agents at 3 concurrent (`max_parallel=3`, configurable). Each Opus agent uses ~30 turns × ~8K tokens = ~240K tokens. Three concurrent agents stay well within API rate limits and keep cost predictable.

**Why 3**: Balances wall-clock improvement against API costs and rate limits. Most changes have 2-3 truly independent tasks. Configurable via `PipelineState` for users who want more/less.

## Risks / Trade-offs

**[Risk] Phase 3 misclassifies task independence** → Tasks touch overlapping files, causing merge conflicts.
→ *Implemented (reactive)*: Merge-time conflict detection in `_run_wave()`. Failed merges are aborted (`git merge --abort`), tasks marked `needs-manual-merge`, conflicts reported to human. Tested in integration tests (task 5.4).
→ *Deferred (preventive)*: Use the test-to-source mapping (Layer 2) and import graph (Layer 1) to detect file overlap *before* running the wave. If two "parallel" tasks share predicted change sets, downgrade to sequential with a warning. This soft pre-check is not yet implemented — it requires persisting ContextBundle to PipelineState and adding issue descriptions to the issue dict (~200 lines total). Blast radius without it is low: one wasted agent run (~$2-4) per misclassification, system recovers gracefully. **Revisit if frequent `needs-manual-merge` results appear in production runs.** See tasks.md section 9.

**[Risk] Merge conflicts after a wave** → Parallel branches can't be cleanly merged.
→ *Mitigation*: Mark as `needs-manual-merge`, don't block remaining merges. Worst case: user resolves 1-2 conflicts manually, which is still faster than sequential execution.

**[Risk] Increased API costs** → Parallel agents can't share context, so each re-reads the codebase independently.
→ *Mitigation*: Each agent gets the full `ContextBundle` (import graph, symbol context) from Phase 2a, so re-exploration is minimal. Cost increase is bounded: same total turns, just concurrent. The `max_parallel` cap prevents runaway spend.

**[Risk] Worktree cleanup on failure** → If a parallel agent crashes, its worktree and branch could leak.
→ *Mitigation*: Wrap each agent in a try/finally that calls `git worktree remove` and `git branch -d`. Register cleanup in `atexit` handler as a safety net.

**[Trade-off] Backward compatibility** → Existing tasks.md files without markers run fully sequential.
→ This is intentional: parallel execution is opt-in via Phase 3 markers. No existing behavior changes.
