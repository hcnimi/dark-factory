## Why

Phase 7 writes code AND tests together using the same Opus agent. When the agent misunderstands a requirement, both the code and tests share the same blind spot — tests pass, but the spec isn't met. This is the fundamental trust problem: code validated by the same agent that wrote it provides weak assurance.

Adversarial decomposition fixes this. A separate agent generates tests from the spec *before* implementation. The implementing agent never sees the spec — it only sees tests to make pass. This is exactly how SWE-bench evaluation works: test authors and solving agents are independent.

## What Changes

- **New Phase 6.5** — test generation phase between issue creation (Phase 6) and implementation (Phase 7)
  - Sonnet SDK call reads the spec and generates two test sets:
    - **Visible tests** — injected into Phase 7 prompt as TDD targets ("make these pass")
    - **Hold-out tests** — hidden from Phase 7, used only in Phase 8 as independent validation
  - Tests are persisted to the pipeline state for downstream phases
- **Phase 7 prompt modification** — implementation agent receives visible tests and must make them pass
- **Phase 8 enhancement** — runs ALL tests including hold-out set; hold-out failures trigger warning + human review (not hard block, since generated tests can themselves be wrong)
- **Pipeline state extension** — `PipelineState` gains fields for visible and hold-out test artifacts

## Capabilities

### New Capabilities
- `test-generation`: Spec-to-test generation phase (Phase 6.5) that produces visible and hold-out test sets from OpenSpec requirements and Gherkin scenarios

### Modified Capabilities
- `dark-factory`: Pipeline gains Phase 6.5 between issue creation and implementation; Phase 7 prompt updated to include visible tests; Phase 8 updated to run hold-out tests with soft-fail semantics

## Impact

- **dark_factory/pipeline.py** — new `run_phase_6_5()` function, Phase 7 prompt changes, phase sequencing update
- **dark_factory/agents.py** — new `call_test_gen()` wrapper (Sonnet, bounded turns, read-only tools)
- **dark_factory/verify.py** — Phase 8 enhanced to distinguish hold-out test failures from regular failures
- **dark_factory/orchestrator.py** — PHASE_NAMES updated, phase routing for 6.5
- **Pipeline state model** — new fields for test artifacts (visible_tests, holdout_tests paths)
- **Effort estimate**: ~150 lines + 1 SDK call
- **Cost**: ~$0.02 per run (1 Sonnet call for test generation)
