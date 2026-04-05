# Interview Transcript

## Round 1: Confirming Key Decisions from Ideation

**Context**: The ideation document established 7 key decisions. This round confirmed them and probed boundaries.

**Q1**: Decision #7 says the evaluator model should be configurable (Opus for complex codebases, parallel Sonnet for simpler ones). Does this extend to the implementation agent too — should the user be able to choose Opus vs Sonnet for the implementation run, or is Opus always the implementer?

**A1**: Opus always implements. Only the evaluator model is configurable.

**Q2**: The ideation lists 6 open questions. Which feel most urgent to nail down in this spec vs. deferring to implementation-time experimentation?

**A2**: All equally important. All 6 open questions need answers before we can spec the architecture.

**Q3**: The current dark-factory has a human checkpoint (Phase 5) where you approve/modify/abort the plan before implementation. In v2's three-component model, where does human oversight fit?

**A3**: Configurable gates. Gates are configurable per-project. Some teams want full autonomy (no gates), others want checkpoints at every boundary.

---

## Round 2: Evaluator Rubric & Fix-Up Loop

**Q1**: For the evaluator rubric: the ideation mentions 'intent fidelity, correctness, integration' as dimensions. For DPPT enterprise Java tickets, what additional dimensions matter?

**A1**: Start with 3 core + iterate. Ship with intent fidelity, correctness, integration. Add domain-specific dimensions through experimentation against real tickets.

**Q2**: On the fix-up loop: currently Phase 7 runs tests after each task and spawns a fix agent on failure. The open question is whether to keep this or let the model run tests itself during implementation.

**A2**: "What's the research say?" — Research presented: Boris lets the model test naturally, Anthropic says computational verification should be deterministic. Hybrid approach recommended and accepted.

**Q3**: The current evaluator-optimizer uses Sonnet for review and Opus for fixes, up to 3 cycles with diminishing-returns exit. Should the loop structure change?

**A3**: "What's the research say?" — Research presented: Anthropic found fixed constructs become unnecessary overhead, simplest approach is best. Single evaluation + optional re-run recommended and accepted.

**Follow-up Q (Fix loop confirmation)**: Given the research, the hybrid approach (model tests during implementation + harness does final deterministic verification) aligns with both Boris's workflow and the 'deterministic verification' principle. Does that land right?

**Follow-up A**: Hybrid (Recommended). Model runs tests during implementation naturally. Harness does a final deterministic test run after implementation completes. Fix agent only spawns if final verification fails.

**Follow-up Q (Eval strategy)**: For the evaluator loop: single scored evaluation (no auto-fix) is simplest. The score becomes the signal. Which trade-off do you prefer?

**Follow-up A**: Single eval + optional re-run. Default is single eval. If scores are borderline (e.g., 5-7/10), offer the user a 'retry with feedback' option rather than auto-fixing.

---

## Round 3: Infrastructure Carryover & Intent Clarification

**Q1**: The current codebase has 19 modules. Do you want to carry forward the actual code, or rewrite from scratch using the same concepts?

**A1**: Rewrite with same concepts. Fresh implementation of state, security, cost, worktrees. Informed by v1 but not inheriting its code. Clean break.

**Q2**: Intent clarification: should it be conversational (like Boris's plan mode) or templated?

**A2**: "Depends on whether input is sufficiently well-defined. If not, interview leads to well-defined plan or spec? What's the research say?" — Research presented: Boris's plan mode IS conversational, but the output format matters more than the input format. Anthropic uses "feature lists with pass/fail tracking." Hybrid approach (accept structured input, interview for gaps) accepted.

**Q3**: Sprint contracts with Opus 4.6: keep, modify, or drop?

**A3**: Drop entirely. Opus 4.6 doesn't need per-task contracts.

**Follow-up Q (Intent output)**: The intent clarifier's output should be a structured document with (1) intent summary, (2) testable acceptance criteria. The standard evaluation rubric is applied by the evaluator, not generated per-ticket. Is this right?

**Follow-up A**: "I'm inclined towards 2 but does output format matter to the extent that the final implementation is what's intended?" — Clarified that acceptance criteria ARE load-bearing because they give the evaluator concrete things to check. Intent + AC confirmed as the output format.

**Follow-up Q (Interview UX)**: When the intent clarifier interviews the user to fill gaps, what's the conversation medium?

**Follow-up A**: Claude Code native. Use AskUserQuestion or inline chat.

---

## Round 4: Per-Project Configuration & Architecture Boundaries

**Q1**: What's the configuration surface?

**A1**: Minimal config file. `.dark-factory/config.yaml` with ~5 knobs, sensible defaults.

**Q2**: What's the actual execution model? Single long-running agent or task-parallel?

**A2**: "What's the research say?" — Research presented: Boris uses parallel agents on SEPARATE features, not within one feature. Anthropic recommends "single feature per session." Multi-agent uses 15x more tokens. Single agent recommended and accepted.

**Q3**: Should deterministic context pre-fetch survive in v2?

**A3**: Drop it, model explores. Trust the model to find what it needs via agentic search.

**Follow-up Q (Single agent confirmation)**: Single SDK agent per feature, scale by running multiple instances. Does this align?

**Follow-up A**: "How do we ensure 1 feature per run/agent?" — This led to scope enforcement discussion.

**Follow-up Q (Cost budget)**: What's the right default cost budget?

**Follow-up A**: "Not ready for budgets." Deferred to implementation.

---

## Round 5: Scope Enforcement

**Q1**: When scope is too large, what's the response?

**A1**: Auto-decompose into sub-runs. The clarifier automatically decomposes large tickets into independent sub-tickets and queues separate runs.

**Q2**: How should the intent clarifier determine if scope is right-sized?

**A2**: "What's the research say?" — Research presented: SWE-bench Pro average is 4.1 files, FeatureBench shows even single features are hard, scope discipline is critical. Acceptance criteria count as primary signal, model self-assessment as secondary. Accepted.

---

## Round 6: Security, State, and Operations

**Q1**: With v2's single agent having more freedom, does the security model need to change?

**A1**: "What's the research say?" — Research: security is infrastructure (keep), more autonomy demands more security. Same security model, ported to v2.

**Q2**: State persistence: what are the meaningful resume points?

**A2**: Continuous checkpointing. Checkpoint periodically during implementation (after each git commit).

**Q3**: Observability: what does the harness need to provide?

**A3**: Full tool call logging. Log every SDK tool call, cost per call, and timing.

---

## Round 7: Edge Cases & Failure Modes

**Q1**: When the implementation agent exhausts its budget or gets stuck, what's the failure UX?

**A1**: "What's the research say?" — Research: Anthropic's pattern is commit progress, evaluate partial work. Preserve progress + evaluate + scored report accepted.

**Q2**: How are auto-decomposed sub-runs coordinated?

**A2**: "What would you suggest based on research?" — Sequential by default. Clarifier orders logically. Later sub-runs see git state from earlier ones. Accepted.

**Q3**: What if the implementation is correct but the original intent was wrong?

**A3**: "I don't understand." — Explained with REST vs. GraphQL example. Clarified: this is the intent clarifier's responsibility. The evaluator scores against stated intent. If intent is wrong, that's an upstream problem.

**Follow-up Q (Confirm R6)**: Preserve progress + evaluate partial work + sequential sub-runs — both sound right?

**Follow-up A**: Both sound right.

**Follow-up Q (Test gap)**: What happens when implementation passes its own tests but fails harness verification?

**Follow-up A**: "What's the research say?" — Research: model has context, separate fix agent lacks it. Re-enter implementation agent with failure output (1 retry). Accepted.

---

## Round 8: Scope Boundaries & Phasing

**Q1**: What's explicitly out of scope for v2?

**A1**: Keep Jira read (not write). Multi-repo, CI integration, Jira write-back, team collaboration, custom tools are all out.

**Q2**: What's the MVP?

**A2**: Intent + implement + eval. Inline description → Opus implementation → evaluation with scores. No Jira, no decomposition, no config.

**Q3**: Should v2 replace v1 or coexist?

**A3**: Replace entirely. v1 archived once v2 works.

---

## Round 9: Implementation Details

**Q1**: Worktree model: single worktree, direct repo, or configurable?

**A1**: Configurable. Default to worktree, `--in-place` for direct repo work.

**Q2**: Evaluator output format?

**A2**: Both. JSON report file + PR review comment.

**Q3**: CLI surface?

**A3**: Run + evaluate only. `dark-factory run` for full flow, `dark-factory evaluate` as standalone.

---

## Round 10: Remaining Details

**Q1**: Does v2 need an init command?

**A1**: Keep init. Creates config with defaults and detects project conventions.

**Q2**: CLI tool or Claude Code skill?

**A2**: Skill-first. Primary invocation through Claude Code skill, CLI available as standalone.

**Q3**: How to handle the over-simplification risk for enterprise codebases?

**A3**: "Not sure, what's the research say?" — Research: agentic search is better for code discovery, convention discovery is different (implicit, scattered). Recommended lightweight pre-flight checks. Accepted with addition of build + deps checks.

**Follow-up Q (Pre-flight scope)**: What additional pre-flight checks beyond test runner, conventions, CLAUDE.md?

**Follow-up A**: Build + deps only. Add dependency installation verification and project build check.

**Q4**: Any requirements, concerns, or constraints not covered?

**A4**: No, we're complete.

---

## Final Confirmation

**Q**: Does the consolidated spec summary accurately capture everything we discussed?

**A**: Accurate, write the spec.
