## 1. State & Routing

- [x] 1.1 Change `PipelineState.current_phase` type from `int` to `float`; add `visible_test_paths: list[str]` and `holdout_test_paths: list[str]` fields to `state.py`
- [x] 1.2 Add `6.5: "Test Generation"` to `PHASE_NAMES` in `orchestrator.py`; update `PHASE_NAMES` key type to `float`
- [x] 1.3 Update `run_phase()` in `pipeline.py` to accept `float` phase numbers

## 2. Test Generation Agent

- [x] 2.1 Add `MAX_TURNS_TEST_GEN = 10` constant and `call_test_gen()` wrapper to `agents.py` (Sonnet, `_sdk_query`, read-only tools)
- [x] 2.2 Implement `run_phase_6_5()` in `pipeline.py`: read spec files, build prompt with Gherkin scenarios, call `call_test_gen()`, parse output into visible and hold-out test content
- [x] 2.3 Add test directory detection heuristic (reuse patterns from `verify.py` fallback detection) and write visible/hold-out test files to worktree with `visible_tests_` / `holdout_tests_` prefixes
- [x] 2.4 Persist test file paths to `PipelineState.visible_test_paths` and `holdout_test_paths`

## 3. Phase 7 Prompt Integration

- [x] 3.1 Modify `run_phase_7()` to read visible test files from `state.visible_test_paths` and inject their content into the per-issue implementation prompt with "Do NOT modify these test files" instruction
- [x] 3.2 Handle empty visible test set gracefully (skip TDD section, fall back to existing behavior)

## 4. Phase 8 Hold-Out Verification

- [x] 4.1 Add `HoldoutResult` dataclass to `verify.py` with `passed: bool`, `failures: list[str]`, `severity: str = "WARNING"`
- [x] 4.2 Implement `run_holdout_tests()` in `verify.py`: execute each hold-out test file individually, collect pass/fail results
- [x] 4.3 Integrate hold-out step into `verify_tests()`: run after main suite passes, return `HoldoutResult` alongside `VerificationResult`
- [x] 4.4 Surface hold-out warnings to human with choices: accept (proceed), investigate (pause), abort

## 5. Pipeline Wiring

- [x] 5.1 Wire Phase 6.5 into the orchestrator's phase sequence (after Phase 6, before Phase 7)
- [x] 5.2 Handle `--resume` at Phase 6.5: skip if already completed, re-run if interrupted
- [x] 5.3 Handle `--dry-run`: Phase 6.5 returns empty test sets without SDK call

## 6. Tests

- [x] 6.1 Unit tests for `call_test_gen()` (mock SDK, verify model/turns/tools config)
- [x] 6.2 Unit tests for `run_phase_6_5()` (spec parsing, test file writing, empty-spec edge case)
- [x] 6.3 Unit tests for `run_holdout_tests()` (pass, fail, empty set, mixed results)
- [x] 6.4 Integration test: Phase 6.5 → Phase 7 → Phase 8 flow with visible + hold-out tests
- [x] 6.5 Test `PipelineState` serialization round-trip with new float phase and test path fields
