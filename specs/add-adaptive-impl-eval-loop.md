# Add Adaptive impl ↔ eval Loop (Stage A)

## Problem

The current pipeline runs `intent → implement → evaluate → PR` once per invocation. On test failure inside `run_implementation`, it allows exactly **one** fix-retry; on evaluation failure, the run completes and ships a PR that the evaluator already flagged as broken. There is no mechanism for the implementation agent to learn from the evaluator's findings and try again.

Three failure modes follow from this fixed shape:

1. **Hard specs fail silently.** A non-trivial spec that needs two or three iterations to converge is currently shipped as a broken PR after one attempt. The evaluator notes the gaps; nothing acts on them.
2. **The pipeline doesn't compound with model capability.** A more capable model could productively iterate against the evaluator's structured feedback. Today the same single-shot shape is used regardless of model.
3. **Failure is invisible until the human reads the eval report.** There is no telemetry distinguishing "succeeded first try" from "succeeded by luck" from "shipped broken."

Stage A from the ideation document (`ideation-llm-driven-orchestration.md`) addresses (1) and (2) by replacing the single fix-retry with a bounded `impl ↔ eval` loop driven by deterministic Python control flow. The evaluator becomes the loop's termination oracle; the implementation agent receives the prior evaluation as feedback context on each retry. Telemetry for (3) is added in the same change so loop-divergence cases are debuggable.

This spec covers Stage A **only**. Stage B (validation-driven follow-up features) and the cross-run outer loop are out of scope and will be specified separately once Stage A has stabilized in production.

## What Changes

- **New loop in `__main__.py`** wrapping the existing `implementation → evaluation` segment: after each evaluation, deterministic termination checks decide whether to launch another implementation iteration with the prior evaluation report as feedback.
- **Termination conditions** (any one terminates): evaluator passes (`is_passing()`), iteration cap reached, total cost would exceed `max_cost_usd` before another iteration could meaningfully run, no improvement across two consecutive iterations, or the same `not_met` criterion set appears twice in a row.
- **Feedback channel**: iterations after the first feed the previous `EvaluationReport` plus a short summary of what changed in the prior diff into the implementation agent's prompt as "what went wrong last time, do not repeat these mistakes."
- **`RunConfig`** gains `max_iterations` (default 3) and `min_iteration_cost_usd` (default $0.50, used only as a budget-fit heuristic). **No new CLI flags are required** for v1; defaults are conservative enough that single-shot specs see no behavioral change.
- **`RunState`** gains an `iterations: list[IterationRecord]` field capturing per-iteration metadata (iteration index, cost, diff line count, evaluation summary, termination reason if applied).
- **JSONL events** gain `iteration_started`, `iteration_complete`, and `loop_terminated` event types. Each carries the iteration index and relevant scores. **Telemetry must land in the same PR as the loop** (non-negotiable per the ideation).
- **`infra.run_implementation`** is refactored: its existing internal fix-retry is removed (the new outer loop subsumes it). Test-pass remains a precondition for evaluation, but a single in-iteration fix attempt is preserved as a cheap recovery before incurring evaluation cost.
- **Gate semantics**: `--gate-eval` fires **after loop convergence**, not after each intermediate iteration. `--gate-intent` is unchanged. (Confirmed per the ideation's open question.)
- **Budget accounting**: `max_cost_usd` is now a **cross-iteration cap**. The loop checks remaining budget before launching the next iteration; if `(remaining_budget < min_iteration_cost_usd)`, the loop terminates with reason `budget_exhausted`. Per-iteration `max_turns` stays as is in `infra.py`.
- The `--resume` flow continues to work: a run gated at `--gate-eval` resumes after the loop has already converged; intermediate iterations cannot be paused at.

**Out of scope** (deferred to follow-up specs):
- Stage B follow-up features (creating scoped follow-up specs from `not_met` criteria)
- Cross-run meta-optimization
- Per-phase budget caps (only total `max_cost_usd` is tracked)
- LLM-driven termination decisions
- Skill extraction / Agent Skills integration

**Breaking changes**: None at the CLI surface. State file schema gains optional `iterations` field; old state files without it deserialize cleanly with `iterations=[]`.

## Requirements

### Adaptive impl-eval loop

#### Requirement: Loop wraps implementation and evaluation

The system SHALL execute implementation and evaluation as a bounded loop. Each loop iteration SHALL run the implementation agent against the current intent (and, on iterations after the first, the prior evaluation feedback), then run the evaluator against the resulting diff. The loop SHALL terminate as soon as any termination condition (see *Termination conditions*) is met.

##### Scenario: Single-iteration convergence (no behavioral change for easy specs)
- **GIVEN** a spec where the first implementation passes evaluation (`EvaluationReport.is_passing()` is true)
- **WHEN** the loop runs
- **THEN** the loop SHALL terminate after iteration 1
- **AND** the total cost and final diff SHALL be within 5% of the pre-Stage-A pipeline's cost and identical in content for the same prompt

##### Scenario: Two-iteration convergence
- **GIVEN** a spec where iteration 1 produces a `not_met` criterion and iteration 2 (with feedback) addresses it
- **WHEN** the loop runs
- **THEN** the loop SHALL terminate after iteration 2 with the iteration-2 diff as the final diff
- **AND** `state.evaluation` SHALL hold the iteration-2 evaluation report

##### Scenario: Iteration cap reached
- **GIVEN** `RunConfig.max_iterations = 3` and a spec that never reaches `is_passing()`
- **WHEN** the loop runs
- **THEN** the loop SHALL execute exactly 3 iterations and terminate with reason `iteration_cap_reached`
- **AND** the final iteration's diff and evaluation SHALL be preserved as `state.diff` and `state.evaluation`

#### Requirement: Feedback context on retries

On every iteration after the first, the implementation agent's prompt SHALL include the previous iteration's `EvaluationReport` (full per-criterion status, scores, and justifications) and a one-line summary of the prior diff (file count and line count). The prompt SHALL frame this content as "what went wrong last time" so the agent does not repeat the same failures. The original intent and original specification SHALL also be passed unchanged on every iteration.

##### Scenario: Iteration 2 receives iteration 1's evaluation
- **GIVEN** iteration 1 completed with an `EvaluationReport` containing one `not_met` criterion
- **WHEN** iteration 2's implementation prompt is built
- **THEN** the prompt SHALL contain the `not_met` criterion text, the evaluator's evidence, and a directive to address it
- **AND** the prompt SHALL also contain the original intent and original specification context unchanged

##### Scenario: Iteration 1 has no feedback section
- **WHEN** the first iteration's prompt is built
- **THEN** the prompt SHALL match the pre-Stage-A implementation prompt byte-for-byte (no feedback section, no "previous attempt" framing)

### Termination conditions

#### Requirement: Pass termination

The loop SHALL terminate immediately after any iteration whose evaluation report satisfies `EvaluationReport.is_passing()` (all dimensions ≥ 8). The terminating iteration's diff and report SHALL be the final outputs.

##### Scenario: Pass on iteration 1
- **GIVEN** iteration 1's evaluation has all three dimensions scoring ≥ 8
- **WHEN** termination is checked after iteration 1
- **THEN** the loop SHALL terminate with reason `passed`

##### Scenario: Pass on iteration 3
- **GIVEN** iterations 1 and 2 had at least one dimension below 8, and iteration 3 has all dimensions ≥ 8
- **WHEN** termination is checked after iteration 3
- **THEN** the loop SHALL terminate with reason `passed` (not `iteration_cap_reached`, even though `max_iterations` was 3)

#### Requirement: Iteration cap

The loop SHALL terminate after the iteration whose 1-based index equals `RunConfig.max_iterations`. The default value SHALL be 3. The cap SHALL be configurable via `RunConfig` but is not required to be a CLI flag in v1.

##### Scenario: Default cap honored
- **GIVEN** `max_iterations` is at its default
- **WHEN** the loop runs against a never-passing spec
- **THEN** the loop SHALL execute exactly 3 iterations

##### Scenario: Cap of 1 reproduces pre-Stage-A behavior
- **GIVEN** `max_iterations = 1`
- **WHEN** the loop runs
- **THEN** the loop SHALL execute exactly 1 iteration regardless of evaluation outcome
- **AND** no feedback context SHALL be assembled (because no second iteration occurs)

#### Requirement: Budget exhaustion

Before launching iteration N (for N > 1), the loop SHALL check whether the remaining budget is sufficient. If `(state.config.max_cost_usd - state.cost_usd) < state.config.min_iteration_cost_usd`, the loop SHALL terminate with reason `budget_exhausted` without launching iteration N. The default `min_iteration_cost_usd` SHALL be $0.50.

##### Scenario: Budget exceeded after iteration 2
- **GIVEN** `max_cost_usd = 10.0`, iteration 2 just completed with cumulative cost $9.80, `min_iteration_cost_usd = 0.50`
- **WHEN** termination is checked
- **THEN** the loop SHALL terminate with reason `budget_exhausted`
- **AND** iteration 3 SHALL NOT be launched

##### Scenario: Mid-iteration budget overrun is honored at next check
- **GIVEN** an iteration whose internal agent run pushes cumulative cost above `max_cost_usd`
- **WHEN** the iteration completes and termination is checked
- **THEN** the existing post-implementation budget logic from `_implement_eval_complete` SHALL still apply (skip evaluation, preserve diff), and the loop SHALL terminate with reason `budget_exceeded_mid_iteration`

#### Requirement: No-improvement termination

The loop SHALL terminate if the most recent two completed iterations show no improvement in acceptance criteria status. Specifically: define `delta_met(N) = met_count(N) - met_count(N-1)` and `delta_not_met(N) = not_met_count(N-1) - not_met_count(N)`. If, after iteration N (with N ≥ 2), `delta_met(N) ≤ 0` AND `delta_not_met(N) ≤ 0`, the loop SHALL terminate with reason `no_improvement`. Raw dimension scores SHALL NOT be used for this check (per the ideation's note that scores have variance; criterion counts are more stable).

##### Scenario: No criteria changed status
- **GIVEN** iteration 2's `met` and `not_met` counts are identical to iteration 1's
- **WHEN** termination is checked after iteration 2
- **THEN** the loop SHALL terminate with reason `no_improvement`

##### Scenario: Criteria moved met → partial (regression)
- **GIVEN** iteration 1 had `met=2, not_met=1` and iteration 2 has `met=1, not_met=1` (one criterion regressed from met to partial)
- **WHEN** termination is checked
- **THEN** `delta_met = -1` and `delta_not_met = 0`, so the loop SHALL terminate with reason `no_improvement`

##### Scenario: Improvement allows continuation
- **GIVEN** iteration 1 had `met=1, not_met=2` and iteration 2 has `met=2, not_met=1`
- **WHEN** termination is checked
- **THEN** `delta_met = +1`, the no-improvement check SHALL NOT trigger, and the loop SHALL continue

#### Requirement: Same-failure-twice termination

The loop SHALL terminate if the set of `not_met` criterion strings on the most recent iteration is non-empty AND identical to the set on the prior iteration. The check uses set equality on the criterion text (the `criterion` field, not `evidence`). This catches the loop-stuck-on-the-same-test failure mode called out in the ideation's risks.

##### Scenario: Same failures repeated
- **GIVEN** iteration 1's `not_met` criteria are `{"A", "B"}` and iteration 2's are `{"A", "B"}`
- **WHEN** termination is checked after iteration 2
- **THEN** the loop SHALL terminate with reason `same_failure_twice`

##### Scenario: Different failures keep loop alive
- **GIVEN** iteration 1's `not_met` was `{"A", "B"}` and iteration 2's is `{"A", "C"}`
- **WHEN** termination is checked
- **THEN** `same_failure_twice` SHALL NOT trigger; other termination conditions still apply

##### Scenario: Empty not_met sets do not trigger
- **GIVEN** iterations 1 and 2 both have empty `not_met` sets but neither passes (because dimension scores are below 8)
- **WHEN** termination is checked
- **THEN** `same_failure_twice` SHALL NOT trigger (empty set comparison is excluded by design — that case is governed by `passed` or `no_improvement`)

#### Requirement: Termination check ordering

When more than one termination condition could apply after the same iteration, the system SHALL evaluate them in this order and emit the first matching reason: `passed`, `budget_exhausted`, `iteration_cap_reached`, `same_failure_twice`, `no_improvement`. This ordering ensures success is recorded even when the iteration cap is hit, and that "stuck" failures are distinguished from "plateaued" ones.

##### Scenario: Pass at the iteration cap
- **GIVEN** iteration 3 passes AND `max_iterations = 3`
- **WHEN** termination is checked
- **THEN** the reason SHALL be `passed`, not `iteration_cap_reached`

##### Scenario: Same failure twice and no improvement both apply
- **GIVEN** iterations 1 and 2 both have `not_met = {"A"}` and `met` counts unchanged
- **WHEN** termination is checked
- **THEN** the reason SHALL be `same_failure_twice` (more specific signal)

### State and persistence

#### Requirement: Per-iteration records on RunState

`RunState` SHALL gain an `iterations: list[IterationRecord]` field. `IterationRecord` SHALL contain: `index` (1-based int), `cost_usd` (float, the cost of that iteration's implementation + evaluation), `diff_line_count` (int), `met_count` (int), `partial_count` (int), `not_met_count` (int), `dimension_scores` (dict[str, int]), `not_met_criteria` (list[str]), and `termination_reason` (str | None — only set on the final iteration). `IterationRecord` SHALL serialize via `to_dict`/`from_dict` consistent with other dataclasses in `types.py`.

##### Scenario: Records appended in order
- **GIVEN** a 3-iteration loop
- **WHEN** the loop completes
- **THEN** `state.iterations` SHALL have length 3 with `index` values [1, 2, 3] in that order
- **AND** only the last record SHALL have a non-null `termination_reason`

##### Scenario: Backward-compatible deserialization
- **GIVEN** a state JSON file written by a pre-Stage-A run (no `iterations` key)
- **WHEN** `RunState.from_dict` is called on it
- **THEN** loading SHALL succeed and `state.iterations` SHALL be `[]`

#### Requirement: Final state mirrors latest iteration

After the loop terminates, `state.diff` SHALL equal the diff from the final iteration and `state.evaluation` SHALL equal the evaluation report from the final iteration. This preserves the existing contract that downstream consumers (PR creation, gate handlers, `--resume` flow) read from these fields.

##### Scenario: state.diff matches final iteration
- **GIVEN** the loop terminates after iteration 2
- **WHEN** the final state is saved
- **THEN** `state.diff` SHALL be byte-identical to the iteration-2 diff captured in the worktree

#### Requirement: Worktree reuse across iterations

All iterations of a single run SHALL share the same worktree and branch. Each iteration's implementation agent SHALL run in the same `work_dir`, accumulating commits on the same `dark-factory/<run_id>` branch. The diff captured at the end of each iteration SHALL be `git diff <base_branch>...HEAD` from the shared worktree, which therefore reflects the cumulative effect of all iterations to that point.

##### Scenario: Iteration 2 builds on iteration 1's commits
- **GIVEN** iteration 1 created commits C1 and C2 on the worktree branch
- **WHEN** iteration 2 starts
- **THEN** iteration 2's agent SHALL see C1 and C2 in `git log`
- **AND** iteration 2's diff SHALL include all changes from C1, C2, and any new commits

##### Scenario: Worktree cleanup unchanged
- **WHEN** the loop terminates and `complete` is called
- **THEN** the existing worktree cleanup behavior in `cmd_complete` SHALL apply unchanged

### Telemetry

#### Requirement: Per-iteration JSONL events (must ship in the same PR)

Each iteration SHALL emit at minimum two events to `<run_id>.events.jsonl`: `iteration_started` (with `iteration_index`) before the implementation agent launches, and `iteration_complete` (with `iteration_index`, `iteration_cost_usd`, `diff_line_count`, `met_count`, `partial_count`, `not_met_count`, and `dimension_scores`) after the evaluation. When the loop terminates, a `loop_terminated` event SHALL be emitted with `final_iteration_index`, `termination_reason`, `total_cost_usd`, and the same per-iteration counts from the final iteration.

This requirement is non-negotiable per the ideation's risk analysis: adaptivity without telemetry creates invisible regressions. The implementation PR for the loop SHALL also include the telemetry; reviewers SHALL reject a PR that lands the loop without these events.

##### Scenario: Three-iteration run emits seven events
- **GIVEN** a three-iteration loop terminating with `same_failure_twice`
- **WHEN** the run completes
- **THEN** the events file SHALL contain (in order): `iteration_started` (1), `iteration_complete` (1), `iteration_started` (2), `iteration_complete` (2), `iteration_started` (3), `iteration_complete` (3), `loop_terminated` (with `termination_reason: "same_failure_twice"`)

##### Scenario: Termination reason matches RunState
- **WHEN** `loop_terminated` is emitted with reason R
- **THEN** the final `IterationRecord.termination_reason` SHALL also equal R
- **AND** the two values SHALL be derived from the same source (no independent computation)

##### Scenario: Existing event types preserved
- **WHEN** the loop runs
- **THEN** the pre-Stage-A `implementation_started`, `implementation_complete`, and `evaluation_complete` events SHALL still be emitted per iteration, so existing log consumers continue to function

### Gate compatibility

#### Requirement: --gate-eval fires after loop convergence

The `--gate-eval` gate SHALL fire exactly once per run, after the loop has terminated. It SHALL receive the final iteration's `EvaluationReport`. Intermediate iterations SHALL NOT trigger gates and SHALL NOT pause for user input or emit `__gate__` JSON.

##### Scenario: Gate sees final report only
- **GIVEN** `--gate-eval` is set and the loop runs three iterations
- **WHEN** the gate is invoked
- **THEN** it SHALL receive only the iteration-3 `EvaluationReport`
- **AND** the loop SHALL NOT have prompted the user or emitted `__gate__` between iterations

##### Scenario: --gate-intent unchanged
- **GIVEN** `--gate-intent` is set
- **WHEN** intent clarification completes
- **THEN** the gate SHALL fire as it does today, before the loop begins, with no change in behavior

#### Requirement: Resume flow handles loop output

`--resume <run_id>` from a `GATED_EVAL` state SHALL load `state.evaluation` and `state.diff` (which by spec hold the final iteration's outputs) and proceed to completion. The resume path SHALL NOT re-enter the loop. Iteration records loaded from disk SHALL be preserved on subsequent saves.

##### Scenario: Resume after loop convergence
- **GIVEN** a run that converged in two iterations and is now `GATED_EVAL`
- **WHEN** `dark-factory run --resume <run_id>` is invoked and the user accepts
- **THEN** the run SHALL complete using the iteration-2 outputs
- **AND** `state.iterations` SHALL still have length 2 after the resume completes

### Backward compatibility and configuration

#### Requirement: Conservative defaults

`RunConfig.max_iterations` SHALL default to 3 and `RunConfig.min_iteration_cost_usd` SHALL default to 0.50. With these defaults, runs whose first iteration passes evaluation (the common case for well-scoped specs) SHALL incur **no additional cost** and **no additional latency** compared to the pre-Stage-A pipeline.

##### Scenario: Easy spec is unchanged
- **GIVEN** a spec that passed in one shot under the pre-Stage-A pipeline
- **WHEN** the same spec runs under Stage A with default config
- **THEN** the run SHALL terminate after iteration 1 with reason `passed`
- **AND** total cost SHALL be within 5% of the pre-Stage-A run's cost

##### Scenario: Disabling the loop
- **GIVEN** `RunConfig.max_iterations = 1`
- **WHEN** the loop runs
- **THEN** behavior SHALL be functionally equivalent to the pre-Stage-A pipeline (one implementation, one evaluation, no retry, no feedback context)

#### Requirement: Removal of legacy in-implementation fix-retry

The in-implementation fix-retry currently in `infra.run_implementation` (the `_launch_fix_agent` call when tests fail) SHALL be replaced by the outer loop's retry mechanism. A single best-effort fix attempt MAY be preserved within an iteration as a cheap test-pass recovery, but the formal "retry on failure" path SHALL be the outer loop. This consolidates retry semantics into one place and prevents double-counting iterations.

##### Scenario: Test failure triggers outer retry, not internal retry
- **GIVEN** iteration 1's implementation produces failing tests AND a non-passing evaluation
- **WHEN** the loop continues to iteration 2
- **THEN** iteration 2 SHALL be a fresh implementation pass with feedback, not a fix-only agent
- **AND** the per-iteration `cost_usd` SHALL include only one implementation agent invocation plus its evaluation (not implementation + fix + evaluation)

## Interview Notes

This spec was generated non-interactively from `ideation-llm-driven-orchestration.md` per user direction (no clarifying questions). Below are the design decisions made and where they came from.

### Pre-validated from ideation (Key Decisions)
- **Q**: Should an LLM agent orchestrate the pipeline?
- **A**: No. Pipeline stays under deterministic Python control. Stage A is loop logic in `__main__.py`, not a meta-agent. Backed by Meta-Harness paper's empirical finding that LLM-driven search converges on deterministic inner pipelines.

- **Q**: Stage A vs Stage B sequencing?
- **A**: Stage A only in this spec. Stage B (follow-up features) and the cross-run outer loop get their own specs once Stage A stabilizes.

- **Q**: Telemetry — separate PR or same PR as the loop?
- **A**: Same PR. Non-negotiable per the ideation's risk analysis: adaptivity without telemetry creates invisible regressions.

### Reasonable calls for ideation's open questions
- **Q**: How to detect "score not improving" given evaluator score variance?
- **A**: Use met/partial/not_met deltas (the ideation's own suggested fallback), not raw scores. Specifically: `delta_met ≤ 0 AND delta_not_met ≤ 0` over two consecutive iterations terminates with reason `no_improvement`.

- **Q**: Does `--gate-eval` fire per iteration or only on convergence?
- **A**: After convergence only. The ideation document assumed this; this spec confirms it.

- **Q**: How is total budget tracked across iterations?
- **A**: `max_cost_usd` becomes a cross-iteration cap. A pre-flight check using `min_iteration_cost_usd` (default $0.50) prevents starting an iteration that can't fit. Per-call `max_turns` is unchanged.

- **Q**: How is "same failure twice" defined?
- **A**: Set equality on `not_met` criterion strings (the `criterion` text, not the `evidence`). Empty sets are excluded — that case is `passed` or `no_improvement`, not `same_failure_twice`.

- **Q**: What is the iteration cap?
- **A**: 3 by default, matching the ideation's sizing analysis ("budget cap on hard specs, ~2-3× token cost vs today on those specs").

- **Q**: What goes into the feedback context for retries?
- **A**: The full prior `EvaluationReport` (per-criterion status with evidence, dimension scores with justifications) plus a one-line summary of the prior diff (file + line count). Original intent and original specification are passed unchanged on every iteration.

### Risk mitigations encoded as requirements
- **Loop divergence** — mitigated by hard iteration cap, budget cap, no-improvement check, and same-failure-twice check (four independent termination conditions).
- **Telemetry-as-afterthought** — encoded as the "Per-iteration JSONL events (must ship in the same PR)" requirement with explicit reviewer guidance.
- **Hidden behavioral change for easy specs** — encoded as the "Conservative defaults" requirement with a 5% cost-parity scenario for first-iteration passes.

### Out of scope (deferred)
- **Q**: Should follow-up features (Stage B) land here?
- **A**: No. Separate spec once Stage A is stable.

- **Q**: Should the cross-run outer loop be addressed?
- **A**: No. Deferred until A+B produce a 20+ run corpus to learn from.

- **Q**: Per-phase budget caps (separate caps for impl vs eval)?
- **A**: Out of scope for v1. Only total `max_cost_usd` is tracked.

- **Q**: New CLI flags for `max_iterations` / `min_iteration_cost_usd`?
- **A**: Not required for v1. Defaults are conservative; advanced users can construct `RunConfig` directly. Adding flags is a trivial follow-up if needed.
