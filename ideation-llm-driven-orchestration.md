# Ideation: Adaptive Pipeline Shaping (Looping + Follow-Up)

> Originally pressure-tested an "LLM-driven orchestration" proposal. Research
> shifted the direction. This file now captures both the original analysis
> (preserved below) and the revised path.

## Terminology

Three terms get conflated in the multi-agent literature. For this project:

| Term | Meaning | Scope in dark-factory |
|---|---|---|
| **Harness** | Wrapping around a *single agent session* — tool access, context mgmt, agent loop, security policy | Each phase (intent, impl, eval) uses the Claude Code SDK as its harness |
| **Pipeline** | A *sequence of phases*, each with its own agent/harness, persistent state between phases | What dark-factory *is* — the multi-phase coding system |
| **Scaffolding** | Supporting instructional/state material around LLM calls — prompts, state files, tools | The prompts and `.dark-factory/<run_id>.*` artifacts inside the pipeline |

dark-factory is **an autonomous coding pipeline that uses the Claude Code SDK as its agent harness in each phase.**

## Problem

The current pipeline is fixed-shape: `intent → implement → evaluate → PR`. Same
every run. Pipeline-shape decisions are CLI flags (`--gate-intent`,
`--analyze-spec`, `--no-assess`) set once at invocation, plus a single fix
retry inside implementation.

This is brittle to spec variance:

| Spec shape | Current pipeline behavior |
|---|---|
| Well-scoped, single feature | Works well (the design point) |
| Vague, needs clarification | Binary `--no-assess` flag — set once, can't iterate |
| Multi-feature spec | No decomposition; one large impl agent attempt |
| Hard / requires iteration | One retry, then ships a broken PR |
| Easy / trivial | All phases run anyway — wasted tokens |

The pipeline also doesn't compound with model capability. Stronger models
inside the phases produce marginally better outputs, but the *shape* doesn't
adapt to make use of that capability (e.g., looping more confidently because
each iteration is more productive).

## Direction (Research-Informed)

Evolve the pipeline to **shape itself adaptively** within deterministic Python
control flow. Two stages, in order, each independently shippable:

### Stage A — Pipeline-Inner Looping

Replace the single fix-retry with an adaptive `impl ↔ eval` loop bounded by
deterministic termination conditions.

- Today: `impl → eval → if fail → one fix retry → done`
- Evolved: `impl → eval → if fail (and budget remains, and score is improving,
  and not stuck on the same test) → impl with feedback → eval → repeat`

What changes:
- `__main__.py` gains loop logic with multiple termination checks
- Each iteration after the first feeds the previous eval report into the impl
  agent's context as "what went wrong last time"
- Termination conditions: budget exhausted, score not improving across two
  iterations, same failure mode twice in a row

What stays the same:
- Phase agents (impl, eval) — unchanged
- Deterministic Python is still in control
- No LLM orchestrator-agent added

### Stage B — Validation-Driven Follow-Up Features

When evaluation reports `not_met` criteria but the overall implementation is
mostly correct, create a *follow-up feature* targeting only the gaps.

- Today: eval report's `not_met` criteria signal failure; whole-pipeline retry
- Evolved: eval report's `not_met` criteria become a scoped follow-up spec;
  fresh impl agent works against the narrow follow-up; re-eval

What changes:
- New phase type: `followup_impl` with scoped input from the eval report
- New deterministic decision: "if N criteria failed and budget remains and
  partial progress was made, create a follow-up"
- The follow-up *content* is LLM-generated (the eval agent already names
  what's missing); the *shape decision* is still Python rules

What stays the same:
- Same evaluator scoring criteria
- Same security/worktree/state plumbing
- Still no LLM orchestrator-agent

### Deferred Opportunity — Cross-Run Outer Loop

After Stages A and B are in production and have produced a corpus of runs,
consider a *cross-run* meta-optimization layer modeled on Lee et al.'s
*Meta-Harness* (arXiv:2603.28052, May 2026):

- An LLM proposer reads `.events.jsonl` + diffs + eval reports across many
  past runs, proposes targeted improvements (prompt edits, retry policy
  adjustments, per-phase budget changes)
- Improvements are reviewable by a human before being applied
- Cross-run learning: the system improves over time from its own history

This is speculative and deferred. It should only be pursued if (a) Stages A
and B prove out, (b) the run corpus is large enough to learn from
(20+ runs), (c) the meta-improvements aren't obvious by inspection.

## Why The Direction Changed

The original four-stage proposal (extract skills → LLM skill selection →
spec_analyzer as tool → orchestrator-agent replaces main) borrowed Factory's
"Missions" pattern wholesale. Research from two independent sources shifted
the recommendation.

### Anthropic's published harness research (2024-2026)

| Source | Stance |
|---|---|
| *Building Effective Agents* (Dec 2024) | Workflows (predefined code paths) vs agents (LLM-directed). Use workflows for predictability. |
| *Multi-Agent Research System* (2025) | *"Prompt engineering was our primary lever."* But also: *"deterministic safeguards like retry logic and regular checkpoints."* |
| *Effective Harnesses for Long-Running Agents* (2026) | *"Even Opus 4.5 in a loop across multiple context windows will fall short [without a well-designed harness]."* Recommends structured state files (JSON), phase-specific prompts, checkpoint commits. |
| *Equipping Agents with Agent Skills* (2026) | Skills as model-discoverable instruction bundles. The SDK supports this natively. |

Net Anthropic position: **prompts/skills for judgment, code for reliability
and durable state.** A hybrid, not Factory's maximalist "almost all
orchestration in prompts."

### Meta-Harness paper (Lee et al., May 2026; arXiv:2603.28052v1)

Empirically tested LLM-driven harness search across text classification,
IMO-level math, and TerminalBench-2 coding.

Findings relevant here:
- Harness design produces large performance gaps (6× in their measurements)
- **The harnesses an LLM-driven search *discovers* are deterministic.** Math
  winner is a 4-way lexical router. Text-classification winner is a
  deterministic 2-call draft/verify.
- LLM-driven decisions live in the *outer search* loop; *inner pipelines* are
  code-driven.
- Filesystem-backed raw run history (grep/cat over event logs) beats
  summarized feedback for the meta-layer.

### Competitor survey (2025-2026 coding agents)

Coding agents have converged on prompt-driven inner agent loops with
deterministic outer harnesses: Claude Code, OpenAI Codex, Cursor Composer,
Aider, Goose. Factory's Missions is the outlier pushing further into
LLM-driven *pipeline-shape* decisions. Devin is the contrarian leaning more
deterministic; Cognition's 2025 retro hints they feel the cost (ambiguity
handling is their headline weakness).

LangGraph/CrewAI represent a real determinism counter-current — but in
*general workflow automation*, not coding agents specifically.

### What this means for dark-factory

- The current architecture (phase-specific LLM agents inside thin Python) is
  already in the recommended zone from both Anthropic's writing and the
  Meta-Harness paper's empirical findings.
- The original Stage 4 (orchestrator-agent replacing `main()`) overshoots
  the consensus. Meta-Harness explicitly found that LLM-driven search
  *converges on* deterministic inner pipelines like the current one.
- The genuine gap is *adaptivity*: the pipeline doesn't loop, doesn't
  decompose, doesn't follow up. Stages A and B fill that gap without
  adopting Factory's maximalism.

---

## Pressure Points (Original Devil's-Advocate Pass)

These pressure points were generated against the original four-stage
proposal. They remain valid analysis; some apply to the revised direction too
(noted inline).

### 1. The "monolithic prompt" premise doesn't hold up against the code

`IMPLEMENTATION_SYSTEM_PROMPT` in `infra.py` is **15 lines**. Not 700.

```python
IMPLEMENTATION_SYSTEM_PROMPT = """\
You are implementing a feature in a software project. You have full access to \
the codebase via Read, Edit, Write, Bash, Glob, and Grep tools.

Your approach:
1. Explore the codebase ...
2. Plan ...
3. Implement ...
4. Write or update tests ...
5. Run tests ...
6. Make git commits ...

Follow the project's existing code style ...
"""
```

If there's a 700-line equivalent here, it's `commands/dark-factory.md`
orchestration logic + the prompt-engineering scattered across `intent.py`
(INTENT_SYSTEM_PROMPT, EXTRACT_INTENT_SYSTEM_PROMPT), `interview.py`,
`evaluator.py`, `spec_analyzer.py`.

**Still relevant to revised direction:** Stages A and B don't need
skill extraction at all. The 15-line system prompt is already fine for
adaptive looping. Skill extraction is no longer in the path.

### 2. Factory's 700-line claim isn't directly portable

Factory's Missions own the *entire developer-facing surface* (Slack triggers,
multi-repo, multi-tool, long-running). Their 700 lines of prompt drive a much
broader scope than dark-factory's "spec → PR for one repo." The
single-source-of-truth research that originally suggested an N=8 hand-labeling
experiment is no longer load-bearing; the revised path (adaptive loop +
follow-up) is empirically grounded by Meta-Harness without requiring custom
measurement first.

### 3. Gate semantics under tree-shaped pipelines (no longer blocking)

The original concern was that Stage 4's orchestrator-agent would create a
tree-shaped pipeline that breaks `--gate-intent`/`--gate-eval`'s linear exit-75
contract. The revised direction keeps a linear pipeline — adaptive looping
and follow-up features fit within the existing gate model (gates fire after
the loop converges, not in the middle of it).

**Still relevant for the deferred cross-run outer loop:** if the
Meta-Harness-style outer loop ever lands, gate semantics will need
re-thinking. Defer that with the outer loop itself.

### 4. New failure modes from adaptivity

Today's flat pipeline has knowable failure modes. Stages A and B add new
failure modes:

- A loop that never converges (mitigated by hard budget cap + same-failure-twice termination)
- A follow-up feature that diverges from the original intent (mitigated by
  scoping follow-up's input to the eval report's `not_met` criteria only)
- Telemetry gaps: which iteration produced which diff, why each iteration
  terminated, what triggered a follow-up

**Mitigation that must land with Stage A:** every loop iteration writes
structured events (iteration number, score, termination reason if applied)
to `.events.jsonl`. Otherwise debugging loop-divergence cases is invisible.

### 5. Token-overhead question

Original concern: a meta-orchestrator's token tax. No longer relevant — the
revised direction doesn't add an orchestrator-agent. But Stages A and B *do*
add token cost in the form of additional impl iterations and follow-up
features.

Sizing:
- Stage A worst case: budget cap (e.g., 3 iterations) on hard specs. ~2-3×
  token cost vs today on those specs; same as today on easy specs.
- Stage B worst case: one follow-up feature on partially-failing specs.
  ~1.5× token cost on those specs; same as today on clean passes.

These are bounded, predictable, and only paid when the alternative is
shipping a broken PR. Net win.

### 6. Skill discovery model (deferred)

Original concern about (a) orchestrator-injected vs (b) agent-discoverable
skills. Revised direction doesn't introduce skills at all. If skills land
later, they should follow the Claude Code SDK's native Agent Skills pattern
(b) — agent-discoverable, no custom loader.

---

## Key Decisions

- **Pipeline stays deterministically controlled.** No LLM orchestrator agent
  replaces `__main__.py`. Backed by Meta-Harness's finding that LLM-driven
  search converges on deterministic inner pipelines.
- **Adaptivity lives in deterministic loop and branching logic** informed by
  LLM agents' outputs (eval reports). The LLM agents stay inside phases.
- **Stage A first, Stage B second.** A is strictly-better and easier;
  B builds on A's loop infrastructure.
- **Every loop iteration logs structured events to `.events.jsonl`.**
  Non-negotiable. Adaptivity without telemetry creates invisible regressions.
- **Skill extraction is dropped** unless and until a specific worker
  needs context-specific guidance that can't go in the existing 15-line
  system prompt. If needed later, use the SDK's native Agent Skills pattern.
- **Cross-run outer loop (Meta-Harness pattern) is deferred** until A+B are
  in production and a 20+ run corpus exists.

## Open Questions

- **Stage A termination heuristics.** Budget cap is obvious. "Score not
  improving across two iterations" — how to compute reliably given that
  evaluator scores have variance? Possibly use met/partial/not_met deltas
  instead of raw scores.
- **Stage B scoping.** When eval flags `not_met` criteria, does the follow-up
  see the full original spec or only the failed criteria? Trade-off:
  full context risks re-doing work; narrow context risks losing constraints
  the original spec implied.
- **Gate semantics under looping.** `--gate-eval` fires after eval. With
  looping, does it fire after each iteration's eval, or only after loop
  convergence? Assumed: after convergence. Worth confirming.
- **Budget accounting.** Today's max_turns=30 for impl is a per-call cap.
  With looping, total budget needs to be a *cross-iteration* cap, not
  per-iteration. Affects `infra.py` and state model.
- **Cross-run learning.** When the corpus exists, what's the smallest
  useful version of an outer loop? Manual prompt review with a structured
  weekly digest, or automated proposer-evaluator, or somewhere between?

## Risks & Concerns

- **Loop divergence.** A poorly-tuned loop wastes budget without converging.
  Mitigated by hard cap + same-failure-twice detection. Verify on test
  specs before shipping.
- **Follow-up feature drift.** A follow-up feature scoped from eval report
  could implement something the original spec didn't actually want. Mitigation:
  re-evaluate against the *original* intent doc, not against the follow-up's
  scoped criteria.
- **Telemetry-as-afterthought.** If event logging is added after the loop,
  early regression signals will be missed. Telemetry must land in the same
  PR as the loop.
- **Premature optimization on cross-run loop.** Don't build the outer
  loop until the corpus exists. Without 20+ varied runs, the proposer
  has nothing to learn from.

## Recommendation

**Ship Stage A first. Land Stage B once A is stable. Defer cross-run outer
loop until A+B produce a corpus worth learning from.**

Stage A is roughly: refactor the impl→eval phase into a loop, add
termination heuristics, add iteration-aware event logging. Probably 2-3 days
of work plus testing. Strictly-better outcome for hard specs; no regression
for easy ones.

Stage B is roughly: add a `followup_impl` phase type, add the
`should_create_followup` decision rule, route eval reports' `not_met`
criteria into the follow-up's input. Maybe 2-3 days plus testing. Bounded
risk because the follow-up is scoped narrowly.

The deferred cross-run loop is the genuinely exciting opportunity, but it's
a research project, not a refactor. Surface it as a discrete future
proposal once the corpus is ready.

## State

state: ready-for-spec
next: scope `/spec-create` to Stage A only — Stage B and the cross-run
outer loop each warrant their own specs

<!--
  Direction shifted based on research findings from:
  - Anthropic harness post (May 2026)
  - Meta-Harness paper (Lee et al., arXiv:2603.28052v1, May 2026)
  - 2025-2026 coding-agent competitor survey

  Original four-stage proposal (skill extraction → LLM skill selection →
  spec_analyzer as tool → orchestrator-agent replaces main) is superseded
  by the revised two-stage direction (adaptive looping + follow-up features)
  with cross-run outer loop deferred.
-->
