## 1. Package scaffold and state management

- [x] 1.1 Create `dark_factory/` package with `__init__.py`, `cli.py`, `pipeline.py`, `state.py`
- [x] 1.2 Implement `PipelineState` dataclass in `state.py` with JSON serialization (`save()`, `load()`) targeting `.dark-factory/<KEY>.json`
- [x] 1.3 Implement `run_phase()` wrapper in `pipeline.py` that records timing, updates `completed_phases`, and saves state on success or failure
- [x] 1.4 Add `SecurityPolicy` dataclass and `enforce_security()` callback in `security.py`

## 2. Step 1 — Deterministic phases (0, 5, 6, 10)

- [x] 2.1 Implement Phase 0 in `cli.py`: arg parsing via regex (`[A-Z]+-\d+` for Jira, path detection, quoted string), `--dry-run`/`--resume` flags, tool availability checks (`command -v`)
- [x] 2.2 Implement Phase 5 (human checkpoint) as a Python function that renders the plan summary and returns the user's decision (approve/modify/abort)
- [x] 2.3 Implement Phase 6 (beads issue creation) in `pipeline.py`: parse `tasks.md`, invoke `bd create` via `subprocess` for each task, capture issue IDs from JSON output
- [x] 2.4 Implement Phase 10 (local dev verification) in `pipeline.py`: detect dev server command, start process, render checklist, wait for user input
- [x] 2.5 Update `commands/dark-factory.md` to delegate Phases 0, 5, 6, 10 to `python3 -m dark_factory` and read JSON output
- [ ] 2.6 Validate Step 1 with a dry-run against a test repo — confirm zero LLM tokens for Phases 0, 5, 6, 10

## 3. Step 2 — Ingestion and context pre-fetch

- [x] 3.1 Implement Phase 1 Jira ingestion in `ingest.py`: MCP call to fetch ticket, extract fields (summary, description, acceptance criteria, labels, components)
- [x] 3.2 Implement Phase 1 file ingestion in `ingest.py`: read file, parse YAML frontmatter if present, extract sections (summary, acceptance criteria, constraints)
- [x] 3.3 Implement Phase 1 inline interview as SDK `query()` call in `ingest.py`: sonnet, `max_turns=5`, no tools, returns structured ticket fields
- [x] 3.4 Implement Phase 2a `prefetch_context()` in `explore.py`: collect repo structure, project metadata (`package.json`/`pyproject.toml`/`go.mod`), CI config, test infrastructure, convention files, recent git history (20 commits + recently added files)
- [x] 3.5 Implement keyword extraction from ticket summary/acceptance criteria and `grep -rl` search against source directory (up to 20 results)
- [x] 3.6 Implement Phase 2b SDK call in `explore.py`: sonnet, `max_turns=15`, `allowed_tools=["Read", "Glob", "Grep"]`, system prompt includes the Phase 2a context bundle
- [x] 3.7 Update `commands/dark-factory.md` to delegate Phases 1 and 2 to Python
- [ ] 3.8 Validate Step 2 with a run against backstage repo — confirm CI config is always in the context bundle

## 4. Step 3 — SDK orchestration loop (Phases 7, 8, 9, 11)

- [x] 4.1 Implement SDK call wrappers in `agents.py`: `call_review()`, `call_implement()`, `call_fix()`, `call_pr_body()` — each with appropriate `model`, `max_turns`, `allowed_tools`, and `can_use_tool`
- [x] 4.2 Implement Phase 7 in `pipeline.py`: for each issue, claim via `bd update --claim`, spawn `ClaudeSDKClient` implementation agent (opus, `max_turns=30`, edit tools, security callback), close via `bd close`, update progress
- [x] 4.3 Implement `interrupt()` guard in Phase 7: custom `is_off_rails()` check during `receive_response()` streaming
- [x] 4.4 Implement Phase 8 in `verify.py`: detect test command (heuristic from project metadata), run autofix (`eslint --fix`, `black`, etc.) before LLM, run tests via `subprocess`, on failure call SDK fix agent (opus, `max_turns=15`), max 2 retries
- [x] 4.5 Implement Phase 9 in `pipeline.py`: get diff via `git diff`, call SDK review agent (sonnet, `max_turns=10`, read-only tools), if NEEDS_WORK call fix agent (opus, `max_turns=10`), max 1 review-fix cycle
- [x] 4.6 Implement Phase 11 in `pr.py`: `git push`, SDK call for PR body (sonnet, `max_turns=3`, no tools), `gh pr create`, worktree cleanup, issue closing
- [x] 4.7 Wire up cost tracking: accumulate `result_msg.total_cost_usd` from every SDK call into `state.total_cost_usd`
- [x] 4.8 Update `commands/dark-factory.md` to delegate Phases 7-11 to Python
- [ ] 4.9 Validate Step 3 with a full pipeline run — confirm model tiering, `max_turns` limits, and security policy enforcement

## 5. Step 4 — Full orchestrator and quality gates

- [x] 5.1 Move Phases 3 (scaffold/spec generation) and 4 (plan review) to Python with SDK calls
- [x] 5.2 Reduce `commands/dark-factory.md` to thin launcher (~50 lines) that calls `python3 -m dark_factory "$ARGUMENTS"`
- [x] 5.3 Add diff-size guard between Phase 9 and Phase 10: compare actual lines changed vs expected (task count × 150), warn if >3x
- [x] 5.4 Add dependency audit step in Phase 8: `npm audit` / `pip-audit` / `go vet` based on detected project type
- [x] 5.5 Add pipeline completion summary: print per-phase table (duration, cost, turns) on success or failure
- [ ] 5.6 Validate full orchestrator with end-to-end run: Jira ticket → PR with all quality gates passing

## 6. Testing and documentation

- [x] 6.1 Add unit tests for `cli.py` input routing (Jira key, file path, inline description, flags)
- [x] 6.2 Add unit tests for `state.py` serialization round-trip and resume logic
- [x] 6.3 Add unit tests for `security.py` policy enforcement (blocked patterns, write boundary, blocked tools)
- [x] 6.4 Add unit tests for `explore.py` `prefetch_context()` against a fixture repo directory
- [x] 6.5 Add integration test: dry-run pipeline against a test repo, verify JSON state file contents and phase timing
