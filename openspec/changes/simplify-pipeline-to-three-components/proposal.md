# Simplify Pipeline to Three Components

## Why

Dark-factory's 15-phase linear pipeline is the primary source of failure. The compound probability problem (15 phases at 90% per-phase reliability = 21% end-to-end success) makes the pipeline its own worst enemy. The orchestration layer encodes assumptions about model limitations that were valid for Sonnet 3.5 but are stale for Opus 4.6.

Anthropic's own research confirms: *"Every component in a harness encodes an assumption about what the model can't do on its own, and those assumptions are worth stress testing."* Their ablation studies show sprint contracts, context isolation, and micro-planning are dead weight with Opus 4.6. The gap between purpose-built harnesses and "just use Claude Code" has compressed from 20+ points to 1-2 points on meaningful benchmarks.

The harness's value has shifted from orchestrating the model's reasoning to providing infrastructure the model shouldn't be responsible for: state persistence, security boundaries, cost control, and computational verification.

## What Changes

Replace the 15-phase pipeline with three focused components:

1. **Intent Clarifier** — Produces a product-level spec with testable acceptance criteria. Accepts input from Jira tickets, spec files, or inline descriptions. Conducts conversational clarification when input is incomplete. Validates scope and auto-decomposes oversized tickets into sequential sub-runs.

2. **Infrastructure Wrapper** — Thin operational layer providing infrastructure the model shouldn't own: worktree isolation, security policy, cost metering, state checkpointing, hooks isolation, and pre-flight environment validation. Launches a single Opus agent for implementation with full tool access and a cost budget. The model drives exploration, planning, and implementation freely.

3. **Scored Evaluator** — GAN-inspired adversarial evaluation. Separate model, fresh context, reads only intent + diff. Scores on three dimensional rubric (intent fidelity, correctness, integration). Produces JSON report + PR review comment. Invocable standalone via `dark-factory evaluate`.

This is a complete rewrite informed by v1 concepts, not an incremental refactor. v1 code is archived once v2 proves itself.

## Impact

### Scope

**In scope:**
- Jira ticket read, spec file input, inline description input
- Conversational intent clarification via Claude Code native UX
- Single-feature implementation by a single Opus agent
- Hybrid testing: model runs tests during implementation, harness does final deterministic verification
- Scored evaluation with dimensional rubric
- PR creation with evaluation summary
- Auto-decomposition of oversized tickets into sequential sub-runs
- Configurable human gates (after intent, after evaluation, or none)
- Standalone evaluator command (`dark-factory evaluate`)
- Pre-flight environment checks (test runner, conventions, deps, build)
- Lightweight project initialization (`dark-factory init`)

**Out of scope:**
- Multi-repo support
- CI integration (triggering/monitoring CI pipelines)
- Jira write-back (updating ticket status)
- Team collaboration features
- Custom tool development
- Parallel task execution within a single feature run

### Affected Systems

- `dark_factory/` package: full rewrite (19 modules replaced)
- `tests/` directory: full rewrite
- OpenSpec specs: new specs for three components replace 13 existing specs
- CLI interface: simplified to `run`, `evaluate`, `init`
- Skill integration: `/dark-factory` skill updated for v2 invocation

### Known Constraints

- Opus 4.6 is the fixed implementation model (not configurable)
- Evaluator model is configurable (Opus or Sonnet)
- No external Python dependencies (same as v1)
- Requires `git` and `gh` CLI tools at runtime
- Claude Agent SDK for LLM calls (provided by Claude Code environment)

### Migration

- v2 replaces v1 entirely (clean break, not coexistence)
- v1 code archived after v2 MVP demonstrates capability
- `.dark-factory/` state directory format changes (not backward-compatible with v1 state files)
- Config file format is new (`.dark-factory/config.yaml`)

### MVP

Inline description input -> single Opus agent implementation -> single evaluation with scores. No Jira input, no auto-decomposition, no config file, no PR creation. Proves the core three-component loop works before committing to full scope.
