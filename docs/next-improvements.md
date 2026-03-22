# Dark Factory: Next Improvements

Prioritized improvements identified from evaluation against the autonomous AI coding landscape (March 2026). Companion to [dark-factory-evolution-options.md](dark-factory-evolution-options.md).

**Date**: 2026-03-15
**Method**: Evaluated against Claude Code Agent SDK, OpenAI Codex, Devin 3.0, Aider, Auggie, SWE-bench top performers, Copilot Coding Agent, Cline, and StrongDM Software Factory.

---

## Implementation Status (2026-03-21)

All 5 priorities are **code-complete with tests** on the `dark-factory-sdk-migration` branch. None have been through real-world validation runs yet.

| Priority | OpenSpec Change | Status | Known Gaps |
|----------|----------------|--------|------------|
| 1. TDD + Hold-Out Tests | `tdd-holdout-tests` | Code-complete, 59 tests | — |
| 2. Input Quality Gate | `dark-factory-sdk-migration` | Code-complete | — |
| 3. Context Engineering | `dark-factory-context-engineering` | Code-complete, 121 tests | Downstream consumption in Phase 7/8/9 deferred |
| 4. Feedback Loops | `dark-factory-sdk-migration` | Code-complete | — |
| 5. Parallel Execution | `parallel-task-execution` | Code-complete, 52 tasks + 12 integration tests | Soft file-overlap pre-check not implemented (see below) |

**Not yet done**: End-to-end validation against real repositories (dry-run and full-run).

---

## Priority 1: TDD + Hold-Out Tests (Phase 6.5)

**Problem**: Phase 7 writes code AND tests together. When the implementing agent misunderstands a requirement, both the code and tests share the same misunderstanding. Tests pass, but the spec isn't met.

**Solution**: Generate tests from the spec *before* implementation, using a separate agent. Split into two sets:

- **Visible tests** — given to the Phase 7 implementing agent as TDD targets ("make these pass")
- **Hold-out tests** — hidden from the implementing agent, used only in Phase 8 as independent validation

**Why this works**: Adversarial decomposition. Agent A (Sonnet, from spec) writes tests for what the code *should do*. Agent B (Opus, from tests) writes code to *make them pass*. Agent B can't misinterpret the spec — it never sees it. This is exactly how SWE-bench works: the evaluation tests are written by the issue author, not the solving agent.

**Architecture**:

```
Phase 6:   Issue creation (existing)
Phase 6.5: Test generation (NEW — 1 Sonnet SDK call)
  ├── visible_tests   → injected into Phase 7 prompt
  └── holdout_tests   → used only in Phase 8 verification
Phase 7:   Implementation (write code to pass visible tests)
Phase 8:   Run ALL tests including hold-out
```

**Design choices**:
- Hold-out agent uses Sonnet (different model personality than Opus implementer) to maximize blind-spot coverage
- Hold-out test failures in Phase 8 trigger a warning + human review, not a hard block — generated tests can themselves be wrong
- Human checkpoint at Phase 5 could optionally review hold-out tests too

**Effort**: ~150 lines + 1 SDK call. **Impact**: Addresses the fundamental trust problem — code validated by the same agent that wrote it.

---

## Priority 2: Input Quality Gate (Phase 1.5)

**Problem**: The pipeline assumes input (requirements, stories, AC) is well-defined. If it isn't, the pipeline confidently builds the wrong thing. Phase 4 reviews the *plan* derived from the spec — if the spec itself is wrong, the review validates a plan for the wrong thing.

**Solution**: LLM-based input quality assessment against Definition of Ready (DoR) and INVEST criteria from `skills/product-patterns/`.

**Why LLM, not deterministic**: The things that matter for input quality are semantic, not structural. Regex can check "is the AC field populated?" but the real question is "are these AC actually testable?" A perfectly formatted user story with vague AC passes all structural checks and still produces garbage.

Cost comparison:
- LLM gate: ~$0.02 per run (1 Sonnet call)
- Bad input missed: $3-8 per wasted pipeline run
- Breaks even if it catches bad input once in 400 runs

**Architecture**:

```
Phase 1:   Ingest → TicketFields
Phase 1.5: Input quality gate (NEW — 1 Sonnet SDK call)
           Evaluates against DoR checklist + INVEST criteria
           → ReadinessReport { score, gaps, suggestions }
           → Human checkpoint: fix / proceed anyway / abort
Phase 2:   Codebase exploration
```

**Scoring**:
- 80-100: Ready — proceed automatically
- 50-79: Gaps found — present to user with choices
- 0-49: Not ready — block until fixed, offer interactive refinement

**Thin deterministic pre-check**: Short-circuit obviously broken input (empty summary, zero AC) before calling Sonnet. But the real gate is the LLM evaluating semantic quality.

**DoR checks** (from `frameworks.md`):
- Business value articulated (As a... I want... So that...)
- INVEST compliant
- Acceptance criteria describe all features of the story
- No external dependencies prevent completion
- Story scope is realistic

**INVEST checks**:
- Independent — no unresolved external dependencies
- Valuable — clear benefit stated, not filler
- Small — not an epic disguised as a story
- Testable — AC are concrete and verifiable

**Effort**: ~100 lines + 1 SDK call. **Impact**: "Garbage in, garbage out" firewall — every downstream phase amplifies input quality problems.

---

## Priority 3: Context Engineering (Phase 2a Enhancement)

**Problem**: Phase 2a collects repo structure, metadata, and keyword-matched files. Phase 2b gives Sonnet 15 turns to explore. But keyword matching finds files that *mention* something — not files that *depend on* something. Top SWE-bench performers (Auggie at 51.8% vs raw SWE-Agent at 45.9%, same model) show that context engineering is the primary differentiator.

**Solution**: Three independent layers of deterministic context, each reducing LLM exploration burden.

### Layer 1: Import Graph (~100 lines)

Trace imports forward and reverse from keyword-matched files to find the dependency neighborhood.

- Parse import statements per language (regex-based, no AST needed)
- Resolve to file paths within the repo
- Reverse lookup: what imports each file
- Output: 2-hop neighborhood graph

**Example**: Ticket mentions `userService`. Keyword grep finds 20 files. Import trace narrows to 6 files in the actual change neighborhood.

### Layer 2: Test-to-Source Mapping (~70 lines)

Convention-based matching to know which tests cover which source files.

- Pattern match: `src/foo/bar.ts` → `tests/foo/bar.test.ts`
- Fallback: scan test file imports for source module references
- Output: `{source_file: test_file | None}`

Used in three places:
1. **Phase 7**: "You're modifying X. Its tests live in Y. Update them."
2. **Phase 8**: Run targeted tests first (fast, focused output), then full suite
3. **Phase 9**: Coverage check — "3 files changed, 2 have tests, 1 missing"

### Layer 3: Symbol Context (~150 lines)

Extract function/class/type signatures from the change neighborhood — the "API surface" view.

- Regex-based extraction of exports, function signatures, type definitions
- No function bodies, no comments — just contracts
- Gives the LLM a developer's mental model without reading entire files

**Example output**:
```
── src/services/userService.ts ──
  class UserService {
    constructor(private db: DatabaseClient, private cache: RedisClient)
    async getUser(id: string): Promise<User | null>
    async createUser(data: CreateUserInput): Promise<User>
  }
  Exports: UserService (default)
  Used by: src/routes/users.ts, src/routes/admin.ts
```

**Combined impact**: ~320 lines of deterministic Python. Phase 2b drops from 15→3 turns. Phase 7 saves ~5 turns on orientation. ~30-40% additional token savings.

**Deferred**: Downstream consumption of test-to-source mapping in Phase 7/8/9 is out of scope for this change — the data is available and reusable, but those phases don't call it yet. Tracked as a separate change.

---

## Priority 4: Feedback Loop Improvements

**Problem**: Validation happens *after* all code is written (Phase 8/9), not *during*. The implementing agent is gone by the time issues are found. Fix agents start cold, reading code they didn't write.

### 4a: Lint-in-Loop (prompt edit only)

Add to Phase 7 implementation prompt:
```
After completing each file change, run the project's lint command: {lint_command}
Fix any errors before moving to the next file.
```

Zero code change. Lint errors caught with warm context get fixed in 1 turn vs 3-5 turns cold.

### 4b: Self-Review Checklist (prompt edit only)

Add structured self-check to end of Phase 7 prompt:
- `git diff --stat` — verify only expected files changed
- grep for debug artifacts (console.log, TODO, FIXME, debugger)
- Confirm test files exist for new/modified source files (using Layer 2 mapping)
- Run lint command, fix remaining issues

Catches 60-70% of what Phase 9 review would find, while the implementation agent still has context.

### 4c: Targeted Tests Between Tasks (~30 lines)

After each issue in Phase 7, run targeted tests for files that task touched:
```python
changed_files = git_diff_names(last_commit)
relevant_tests = [test_mapping[f] for f in changed_files if f in test_mapping]
run_targeted_tests(relevant_tests)
```

Catches regressions per-task instead of at the end. Phase 8 still runs the full suite as final gate.

**Note**: Do NOT add more review-fix cycles. Data from SWE-bench shows diminishing returns after 2-3 iterations. The fix is *earlier and more targeted* feedback, not *more* feedback.

---

## Priority 5: Parallel Task Execution (Phase 7 Restructure)

**Problem**: Phase 7 processes issues sequentially. Each gets 30 turns and shares context. By task 4, earlier tasks crowd the context window. If task 3 breaks something, task 4 inherits the broken state.

**Solution (Level 1 — parallel-safe tasks only)**:

1. Add dependency markers to Phase 3 task generation: `[independent]` / `[depends: N]`
2. Parse in Phase 6's issue creation
3. Run independent tasks via `asyncio.gather` (separate SDK subprocesses)
4. Run dependent tasks sequentially after

```
Phase 7 (current):    issue1 → issue2 → issue3  (serial, shared context)
Phase 7 (parallel):   ┌─ agent1: issue1
                       ├─ agent2: issue3
                       └─ (wait)
                       ↓
                       agent3: issue2 (depends on 1)
```

**Why Level 1 first**: No branch-merge complexity. If Phase 3 classifies independence correctly, file conflicts should be rare. Graduate to branch-per-task (Level 2) or full Agent Teams (Level 3) if needed.

**Effort**: ~80 lines + prompt edit. **Impact**: Wall-clock time reduction proportional to independent task count.

**Known gap — soft file-overlap pre-check**: The design doc describes using the import graph (Layer 1) and test-to-source mapping (Layer 2) to predict file overlap between parallel tasks *before* launching them, downgrading to sequential if overlap is detected. This preventive check is **not implemented**. Merge-time conflict detection (reactive) is implemented and tested — failed merges are aborted, tasks marked `needs-manual-merge`, and conflicts reported to the human.

- **Risk**: Low. Misclassification costs ~$2-4 in wasted Opus tokens per incident. The system recovers gracefully.
- **Prerequisites to implement**: Persist ContextBundle to PipelineState (~30 lines), add issue descriptions to issue dict (~50 lines), then ~120 lines for prediction + overlap logic.
- **Signal to prioritize**: Frequent `needs-manual-merge` results in production runs.

---

## Additional Improvements (Unprioritized)

### Human Interjection Points

Current pipeline has one interaction point (Phase 5). Add checkpoints:
- Between each issue in Phase 7 (review before next task)
- After Phase 8 test results (fix / skip / override)
- After Phase 9 review findings (accept / dispute)

Simplest approach: more `render_checkpoint()` calls (Option A). Long-term: restructure so the slash command orchestrates phase-by-phase, returning control to user between phases (Option C).

### Progress Bridging Across Context Windows

Anthropic's long-running agent harness uses `claude-progress.txt` to persist learnings across context window resets. Add a "learnings so far" field to `PipelineState` so resumed agents don't start cold.

### Real-Time Cost Tracking

Current `CompletionSummary` reports costs after the fact. Add per-phase token burn tracking that can abort if a phase consumes disproportionate budget.

### Web Fetch for Documentation

Phase 2 collects local context but doesn't fetch API docs, library changelogs, or migration guides referenced in the ticket. Add web fetch to Phase 2b's tool set.

---

## Scorecard vs Field

| Dimension | Baseline | Current (2026-03-21) | Target | Best in Class |
|-----------|:--------:|:--------------------:|:------:|:-------------:|
| Orchestration design | 9/10 | 9/10 | 9/10 | 9/10 (Anthropic harness) |
| Model routing | 8/10 | 9/10 | 9/10 | 9/10 (Aider architect/editor) |
| Input validation | 2/10 | 8/10 | 8/10 | 8/10 (StrongDM spec validation) |
| Context engineering | 5/10 | 8/10 | 8/10 | 9/10 (Auggie Context Engine) |
| Test strategy | 4/10 | 8/10 | 8/10 | 9/10 (SWE-bench hold-out) |
| Parallel execution | 3/10 | 7/10 | 7/10 | 8/10 (Agent Teams, Codex) |
| Feedback loops | 5/10 | 8/10 | 8/10 | 8/10 (Devin re-planning) |
| Safety/security | 8/10 | 8/10 | 8/10 | 8/10 (Copilot scanning) |
| Human oversight | 5/10 | 8/10 | 8/10 | 8/10 |
| Resumability | 7/10 | 8/10 | 8/10 | 8/10 (Anthropic progress files) |
| Cost efficiency | 7/10 | 8/10 | 8/10 | 8/10 |
| **Overall** | **5.7** | **8.1** | **8.1** | **8.4** |

*Current scores reflect code-complete implementation. Scores may adjust after real-world validation.*

---

## Sources

- [Effective harnesses for long-running agents (Anthropic)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Claude Code Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Agent Teams — Claude Code](https://code.claude.com/docs/en/agent-teams)
- [SWE-bench Verified leaderboard (Vals.ai)](https://www.vals.ai/benchmarks/swebench)
- [Auggie tops SWE-Bench Pro (Augment Code)](https://www.augmentcode.com/blog/auggie-tops-swe-bench-pro)
- [Devin's 2025 Performance Review (Cognition)](https://cognition.ai/blog/devin-annual-performance-review-2025)
- [StrongDM Software Factory (Simon Willison)](https://simonwillison.net/2026/Feb/7/software-factory/)
- [The Five Levels: Spicy Autocomplete to Dark Factory (Dan Shapiro)](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/)
- [Harness engineering — leveraging Codex (OpenAI)](https://openai.com/index/harness-engineering/)
- [Aider architect/editor pattern](https://aider.chat)
