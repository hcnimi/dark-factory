## Context

Dark Factory's pipeline runs Phases 0–11. Phase 7 (Implementation) uses an Opus agent that writes both code and tests in the same session. Phase 8 (Test Verification) runs those tests. The problem: if the Opus agent misunderstands a requirement, both code and tests share the blind spot — tests pass but the spec isn't met.

Current pipeline state model (`dark_factory/state.py`) tracks phases as integers with `current_phase` and `completed_phases`. Phase routing uses integer keys in `PHASE_NAMES` (orchestrator.py). SDK calls go through `agents.py` wrappers (`_sdk_query` for bounded tasks, `_sdk_client_query` for long-running with interrupt).

## Goals / Non-Goals

**Goals:**
- Generate tests from the spec *before* implementation, using a separate Sonnet agent (Phase 6.5)
- Split generated tests into visible (TDD targets for Phase 7) and hold-out (independent validation in Phase 8)
- Hold-out failures produce warnings + human review, not hard blocks
- Fit cleanly into the existing phase routing without disrupting Phases 0–6 or 9–11

**Non-Goals:**
- AST-based test generation — Sonnet generates idiomatic test code from Gherkin scenarios
- Replacing Phase 8's existing test infrastructure — hold-out tests augment, not replace
- Generating tests for non-spec work (e.g., refactoring tickets with no AC)
- Mutation testing or coverage metrics — future improvement

## Decisions

### D1: Phase numbering — use float key "6.5" in state, not renumber

Phase routing uses `int` keys in `PHASE_NAMES` and `current_phase`. Options:
- **(A) Renumber all phases 7–11 to 8–12** — clean but breaks `--resume` for any in-flight pipelines, changes every downstream reference
- **(B) Use string key "6.5"** — `PHASE_NAMES` already uses `dict[int, str]` but `current_phase` is an int

**Decision**: Change `current_phase` type to `float` and use `6.5`. PHASE_NAMES becomes `dict[float, str]`. Existing integer keys remain valid (6 == 6.0). This is the smallest change and preserves `--resume` compatibility — a state file with `current_phase: 7` still works.

### D2: Test generation agent — Sonnet via `_sdk_query` (bounded, read-only)

The test generation agent needs to read the spec and produce test code. It doesn't need to run tests or edit files — the orchestrator writes the output.

**Decision**: New `call_test_gen()` in `agents.py` using `_sdk_query` (not `_sdk_client_query`). Sonnet, max_turns=10, read-only tools (TOOLS_REVIEW). The orchestrator writes the returned test files to the worktree.

Alternative considered: using `_sdk_client_query` with interrupt guard. Rejected — test generation is a bounded task (spec in, tests out), no risk of runaway loops.

### D3: Test artifact storage — files in worktree, paths in PipelineState

Options:
- **(A) Store test content in PipelineState JSON** — bloats state, awkward for large test suites
- **(B) Write test files to worktree, store paths in state** — tests are real files the implementer/verifier can use directly

**Decision**: (B). The orchestrator writes two files to the worktree:
- `<test_dir>/visible_tests_<source_id>.py` (or `.test.ts` etc., matching project conventions)
- `<test_dir>/holdout_tests_<source_id>.py`

PipelineState gains two new fields:
```python
visible_test_paths: list[str] = field(default_factory=list)
holdout_test_paths: list[str] = field(default_factory=list)
```

Test directory is detected from project conventions (same heuristic as test command detection).

### D4: Visible tests injected into Phase 7 prompt, not the system prompt

The Phase 7 implementation prompt (`pipeline.py:run_phase_7`) already contains per-issue context. Visible tests are appended as a new section:

```
## TDD Tests (make these pass)
The following tests were generated from the spec. Your implementation MUST make them pass.
Do NOT modify these test files.

<test file paths and content>
```

Alternative: inject via system prompt. Rejected — system prompt is shared across all issues; visible tests may be issue-specific.

### D5: Hold-out test execution — Phase 8 runs them separately with soft-fail

Phase 8 (`verify.py:verify_tests`) currently runs the project's test command. Hold-out tests are executed as a separate step after the main test suite passes:

1. Main test suite (existing behavior) — hard fail, triggers fix retries
2. Hold-out tests (new) — run individually, failures produce a `HoldoutResult` with `WARNING` severity
3. Hold-out warnings are surfaced to the human but do NOT block the pipeline

**Rationale**: Generated tests can themselves be wrong. A hold-out failure means "the implementing agent may have missed something" — not "the code is broken." Human judgment is needed.

### D6: Use Sonnet (not Opus) for test generation — model diversity maximizes blind-spot coverage

The implementing agent is Opus. Using a different model (Sonnet) for test generation means different "reasoning personality" — Sonnet may catch edge cases Opus doesn't think to test, and vice versa. This is the same principle SWE-bench uses: evaluation authors ≠ solving agents.

## Risks / Trade-offs

**[Generated tests may be wrong or flaky]** → Hold-out failures are warnings, not blocks. Human reviews both the hold-out tests and the failures before deciding.

**[Phase 6.5 adds ~$0.02 and ~10s to every run]** → Trivial cost. The alternative (wasted $3–8 pipeline run from undetected spec misunderstanding) breaks even after 1/400 catches.

**[Visible tests constrain the implementer]** → By design. The implementer should implement what the spec says, not what it thinks the spec says. If visible tests are wrong, the implementer will fail, and the human checkpoint catches it.

**[Float phase numbering is unconventional]** → Contained to state serialization and PHASE_NAMES lookup. All phase routing logic already uses dict lookups, not range checks. If we add more intermediate phases later, we can renumber in a future migration.

**[Test file naming collisions]** → Source ID is unique per pipeline run. Files are written to the project's test directory with a `visible_tests_` / `holdout_tests_` prefix to avoid clashing with existing tests.
