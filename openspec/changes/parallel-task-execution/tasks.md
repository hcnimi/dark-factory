## 1. Dependency Marker Parsing

- [x] 1.1 Extend `parse_tasks_md()` in `issues.py` to extract `[P]` and `[depends: N, ...]` markers, returning a list of `ParsedTask(index, title, dependencies)` instead of plain strings
- [x] 1.2 Implement backward-compatible default: unmarked tasks depend on previous task (N-1), first unmarked task is independent
- [x] 1.3 Add tests for marker parsing: `[P]`, `[depends: 2]`, `[depends: 1, 3]`, no marker, mixed formats

## 2. DAG Construction and Wave Resolution

- [x] 2.1 Create `TaskDAG` class in `issues.py` with `add_task()`, `validate()`, and `resolve_waves()` methods
- [x] 2.2 Implement cycle detection and invalid-reference validation, raising `CyclicDependencyError` / `InvalidDependencyError`
- [x] 2.3 Implement topological-sort wave resolution that groups tasks by dependency depth
- [x] 2.4 Add `map_to_issues()` method that replaces 1-based task numbers with issue IDs in resolved waves
- [x] 2.5 Add tests for: all-parallel (single wave), linear chain (N waves), diamond dependency, cycle detection, invalid reference, self-reference

## 3. Worktree Management

- [x] 3.1 Create `create_parallel_worktree(repo_root, issue_id)` function that runs `git worktree add` with branch `parallel/{issue_id}`
- [x] 3.2 Create `remove_parallel_worktree(worktree_path, branch_name)` with try/finally cleanup
- [x] 3.3 Register `atexit` handler to clean up any remaining parallel worktrees on unexpected exit
- [x] 3.4 Add tests for worktree creation, cleanup on success, and cleanup on failure

## 4. Wave Execution in Phase 7

- [x] 4.1 Add `max_parallel` field to `PipelineState` (default 3)
- [x] 4.2 Refactor `run_phase_7()` to detect whether dependency markers are present; if none, preserve existing sequential loop
- [x] 4.3 Implement `_run_wave()` that executes a list of tasks concurrently via `asyncio.gather`, each in its own worktree (single-task waves use main worktree directly)
- [x] 4.4 Implement sub-wave batching when wave size exceeds `max_parallel`
- [x] 4.5 Wire wave execution: iterate waves in order, call `_run_wave()` for each, merge results between waves

## 5. Branch Merging

- [x] 5.1 Create `merge_parallel_branch(main_worktree, branch_name)` that runs `git merge --no-edit`
- [x] 5.2 Handle merge conflicts: `git merge --abort`, mark task as `needs-manual-merge`, continue with remaining branches
- [x] 5.3 Add `merge_conflicts` field to `Phase7Result` containing issue IDs and branch names of conflicting tasks
- [x] 5.4 Add tests for clean merge, conflict handling, and multiple conflicts in one wave

## 6. Error Isolation

- [x] 6.1 Wrap each parallel agent in `asyncio.gather(..., return_exceptions=True)` so one failure doesn't cancel others
- [x] 6.2 Track failed task IDs per wave; skip dependent tasks in later waves with status `skipped_dependency_failed`
- [x] 6.3 Add tests for: one failure in a wave (others succeed), dependent task skipped, independent task unaffected

## 7. Phase 3 Prompt Update

- [x] 7.1 Update Phase 3 task generation prompt to instruct the LLM to classify task independence and emit `[P]` / `[depends: N]` markers
- [x] 7.2 Add examples of correct marker usage to the prompt

## 8. Integration Testing

- [x] 8.1 Add dry-run integration test: full pipeline with parallel markers produces correct wave execution order
- [x] 8.2 Add dry-run integration test: pipeline without markers preserves sequential behavior

## 9. Deferred: Soft File-Overlap Pre-Check

Preventive check to catch misclassified task independence before launching parallel agents. Currently, conflicts are detected reactively at merge time (section 5). This pre-check is a cost optimization (~$2-4 saved per misclassification), not a correctness requirement. Prioritize if frequent `needs-manual-merge` results appear in production.

- [ ] 9.1 Persist ContextBundle to PipelineState so import graph survives from Phase 2a to Phase 7
- [ ] 9.2 Add issue description field to issue dict (upstream change in Phase 6 issue creation)
- [ ] 9.3 Implement per-task file prediction using keywords from issue descriptions + import graph neighborhood
- [ ] 9.4 Add pairwise overlap detection in `_run_wave()` before launching parallel agents
- [ ] 9.5 Downgrade overlapping tasks to sequential with warning log
