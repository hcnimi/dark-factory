## ADDED Requirements

### Requirement: Execute wave tasks concurrently
The system SHALL execute all tasks within a wave concurrently using `asyncio.gather`. Each concurrent task SHALL run in its own isolated git worktree. Waves SHALL execute in order — wave N+1 starts only after all tasks in wave N complete (or fail).

#### Scenario: Single-task wave
- **WHEN** a wave contains exactly one task
- **THEN** the system SHALL execute it directly in the main worktree without creating an additional worktree or branch

#### Scenario: Multi-task wave
- **WHEN** a wave contains tasks A, B, and C
- **THEN** the system SHALL create worktrees for each, launch all three via `asyncio.gather`, and wait for all to complete before proceeding to the next wave

#### Scenario: Sequential wave execution
- **WHEN** wave 0 completes and wave 1 is ready
- **THEN** wave 1 tasks SHALL see the merged results of all wave 0 tasks in the main worktree

### Requirement: Concurrency limit
The system SHALL enforce a configurable maximum number of concurrent agents per wave (`max_parallel`, default 3). When a wave has more tasks than `max_parallel`, the system SHALL batch them into sub-waves of at most `max_parallel` size.

#### Scenario: Wave within limit
- **WHEN** a wave has 2 tasks and `max_parallel` is 3
- **THEN** both tasks SHALL run concurrently in a single batch

#### Scenario: Wave exceeds limit
- **WHEN** a wave has 5 tasks and `max_parallel` is 3
- **THEN** the first 3 tasks SHALL run concurrently, and after they complete, the remaining 2 SHALL run concurrently

#### Scenario: Custom limit
- **WHEN** `max_parallel` is set to 1 via `PipelineState`
- **THEN** all tasks SHALL execute sequentially regardless of wave grouping

### Requirement: Worktree isolation for parallel agents
The system SHALL create a temporary git worktree and branch for each parallel agent. The worktree SHALL be branched from the current HEAD of the main worktree. Worktrees and branches SHALL be cleaned up after use. Worktree path computation SHALL resolve symlinks via `Path.resolve()` before deriving sibling directory names, to prevent path mismatches when the repo root contains symlinks (e.g., Homebrew, pyenv, or mounted volumes).

#### Scenario: Worktree creation
- **WHEN** a parallel agent starts for issue "beads-042"
- **THEN** the system SHALL run `git worktree add` to create a worktree at a temporary path with branch name `parallel/beads-042`

#### Scenario: Worktree cleanup on success
- **WHEN** a parallel agent completes successfully
- **THEN** the system SHALL remove the worktree via `git worktree remove` and delete the branch via `git branch -d`

#### Scenario: Worktree cleanup on failure
- **WHEN** a parallel agent crashes or raises an exception
- **THEN** the system SHALL still remove the worktree and branch in a `finally` block

#### Scenario: Cleanup safety net
- **WHEN** the pipeline process exits unexpectedly
- **THEN** an `atexit` handler SHALL attempt to remove any remaining parallel worktrees

#### Scenario: Symlinked repo root
- **WHEN** the repo root path contains symlinks (e.g., `/opt/homebrew/Cellar/...` symlinked from `/usr/local/...`)
- **THEN** the system resolves to the canonical path via `Path.resolve()` before computing the worktree sibling directory location

### Requirement: Merge parallel branches after wave completion
The system SHALL merge each parallel branch back into the main worktree sequentially after all agents in the wave finish. The merge SHALL use `git merge --no-edit`.

#### Scenario: Clean merge
- **WHEN** two parallel branches modify non-overlapping files
- **THEN** both branches SHALL merge cleanly into the main worktree

#### Scenario: Merge conflict
- **WHEN** a branch cannot be merged cleanly
- **THEN** the system SHALL abort the merge (`git merge --abort`), mark the task as `needs-manual-merge`, and continue merging remaining branches

#### Scenario: Multiple conflicts in one wave
- **WHEN** branches B and C both conflict
- **THEN** both SHALL be marked `needs-manual-merge` and reported to the user; branch A (if clean) SHALL still be merged

#### Scenario: Conflict report
- **WHEN** one or more branches have merge conflicts after a wave
- **THEN** the system SHALL include a `merge_conflicts` list in `Phase7Result` with the issue IDs and branch names of conflicting tasks

### Requirement: Error isolation between parallel tasks
A failing parallel task SHALL NOT prevent other tasks in the same wave from completing. Dependent tasks in later waves SHALL be skipped if their dependency failed.

#### Scenario: One task fails in a wave
- **WHEN** task A fails and tasks B and C succeed in the same wave
- **THEN** tasks B and C results SHALL be merged; task A's worktree SHALL be cleaned up; task A SHALL be marked as failed in `Phase7Result`

#### Scenario: Dependent task skipped
- **WHEN** task 1 fails in wave 0 and task 3 depends on task 1
- **THEN** task 3 SHALL be skipped in its wave with status `skipped_dependency_failed` and reason identifying task 1

#### Scenario: Independent task unaffected by failure
- **WHEN** task 1 fails in wave 0 and task 4 is independent (in wave 0 or later)
- **THEN** task 4 SHALL execute normally regardless of task 1's failure

### Requirement: Backward-compatible sequential fallback
When no tasks have dependency markers (`[P]` or `[depends: N]`), the system SHALL execute all tasks sequentially in the original `for issue in issues` loop, identical to current behavior.

#### Scenario: No markers present
- **WHEN** tasks.md contains no `[P]` or `[depends: N]` markers
- **THEN** the system SHALL execute tasks sequentially in listed order, using the main worktree without creating parallel branches

#### Scenario: Mixed old and new tasks.md
- **WHEN** some tasks have markers and some do not
- **THEN** unmarked tasks SHALL default to sequential (depend on previous task) per the dependency graph spec
