## Why

Phase 7 processes implementation tasks sequentially in a shared context window. By task 4, earlier tasks crowd the context, and if task 3 breaks something, task 4 inherits the broken state. Independent tasks (touching different files/modules) could run concurrently, reducing wall-clock time proportionally.

The groundwork already exists — `parse_tasks_md()` recognizes `[P]` parallel markers, the pipeline is fully async, and all three context engineering layers are in place. What's missing is the orchestration: classifying task independence, running parallel tasks via `asyncio.gather`, and sequencing dependent tasks after.

## What Changes

- Phase 3 (task generation) adds dependency markers: `[P]` (parallel/independent) and `[depends: N]` (sequential, blocked by task N)
- Phase 6 (issue creation) parses dependency metadata and stores it on issues
- Phase 7 (implementation) groups tasks into waves: independent tasks run concurrently via separate SDK subprocesses, dependent tasks run sequentially after their blockers complete
- Each parallel agent gets its own worktree branch to avoid file conflicts
- A merge step reconciles parallel branches back into the main worktree after each wave

## Capabilities

### New Capabilities
- `task-dependency-graph`: Parse dependency markers from tasks.md, build a DAG, and resolve execution waves (which tasks can run in parallel, which must wait)
- `parallel-orchestration`: Run independent tasks concurrently via `asyncio.gather` with separate SDK subprocesses, merge results, and sequence dependent tasks

### Modified Capabilities
_(no existing specs to modify)_

## Impact

- **`dark_factory/pipeline.py`**: Phase 7 orchestration changes from `for issue in issues` loop to wave-based execution with `asyncio.gather`
- **`dark_factory/issues.py`**: Extended `parse_tasks_md()` to parse `[depends: N]` markers; issue creation stores dependency metadata
- **Phase 3 prompt**: Updated to instruct the planner to classify task independence and emit markers
- **Worktree management**: Parallel agents need isolated branches; adds git branch creation and merge logic
- **Error handling**: A failing parallel task must not block unrelated parallel tasks in the same wave; dependent tasks in later waves must abort if their blocker failed
