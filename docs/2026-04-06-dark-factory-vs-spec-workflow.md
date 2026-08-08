# Dark Factory vs Spec-Workflow: Comparison Through the Anthropic Harness Lens

**Date:** 2026-04-06

Anthropic ran experiments on their agent harness, removing components one by one and measuring impact. Their conclusion: most framework components encode assumptions about what the model cannot do — and with Opus 4.6, those assumptions have gone stale. All an agent harness actually needs is agents for **planning**, **generation**, and **evaluation**. This document compares dark-factory and ai-dev's spec-workflow plugin against those findings.

---

## Core Intent

| | **Dark Factory** | **Spec-Workflow (ai-dev)** |
|---|---|---|
| **Goal** | Autonomous spec-to-PR pipeline — push-button automation | Staged, decision-driven development — semi-automated with human judgment at every handoff |
| **Philosophy** | "Give it a ticket, get a PR" | "Externalize decisions before implementation starts" |
| **Automation level** | High — optional human gates | Low — human reviews output between every phase |

---

## Planning

This is where Anthropic's findings hit hardest.

### Dark Factory

Planning is **high-level intent extraction**: title, summary, and 3-7 acceptance criteria. The Opus agent explores and plans during implementation. No micro-task sharding, no dependency DAGs in the current v2. The original 12-phase README described detailed planning, but the actual code simplified to intent → implement → evaluate.

### Spec-Workflow

Goes the opposite direction: a **deep, multi-round interview** that probes assumptions, constraints, edge cases, and tradeoffs before any code is written. Produces full OpenSpec artifacts (proposal, capability specs with Gherkin scenarios, design doc, task breakdown). The docs explicitly say "it is better to ask too many questions than too few."

### Anthropic's Verdict

Anthropic found that micro-detailed planning causes cascading failures — "a single error would cascade through every level of implementation, making it hard for the agent to deviate and fix issues on its own." Spec-workflow's detailed specs risk this. However, spec-workflow's specs are *product-level* (user stories, acceptance criteria, Gherkin scenarios), not *implementation-level* (file paths, function signatures). The transcript says plans should "go big on scope" and stay at the "product level, not the implementation level." Spec-workflow arguably does this better than it first appears, since the interview captures *what* and *why*, not *how*.

---

## Generation

### Dark Factory

Single Opus agent, 30 turns, full tool access within an isolated worktree. One shot at the whole feature. Hybrid test feedback with one retry on failure.

### Spec-Workflow

Task-by-task implementation via `/implement` — each beads issue gets its own session. The `/orchestrate` plugin can parallelize non-overlapping tasks via subagents.

### Anthropic's Verdict

Opus 4.5/4.6 doesn't suffer context anxiety, so dark-factory's monolithic approach (one agent, one session, whole feature) is now viable. Spec-workflow's session-per-task isolation was designed for weaker models. With Opus 4.6, dark-factory's approach is more aligned with current model capabilities.

---

## Evaluation

**Both** implement the transcript's core recommendation: the agent that writes code should not evaluate it.

### Dark Factory

Fresh Sonnet evaluator sees only intent + diff (never the implementation conversation). Scores on 3 dimensions (0-10): Intent Fidelity, Correctness, Integration. Each acceptance criterion assessed as met/partial/not_met with evidence. Borderline detection triggers re-run offer.

### Spec-Workflow

`/cold-review` runs in a forked context with no memory of implementation. Categorizes findings as Critical/Important/Suggestion. But uses **pass/fail**, not scored evaluation.

### Anthropic's Verdict

Anthropic specifically advocates **graded evaluation** with scoring rubrics, not just pass/fail. Dark Factory's 0-10 scoring with dimension-specific rubrics directly implements this. Spec-workflow's cold-review is conceptually right (fresh context, adversarial) but lacks the rigor of scored evaluation.

---

## Alignment Summary

| Component | Anthropic says... | Dark Factory | Spec-Workflow |
|---|---|---|---|
| **High-level planning** | Keep it product-level, not implementation-level | Yes — intent extraction only | Mixed — deep but product-focused |
| **Separate evaluator** | Never self-evaluate | Yes — fresh Sonnet, intent+diff only | Yes — cold-review in forked context |
| **Graded evaluation** | Scored rubrics, not pass/fail | Yes — 0-10 on 3 dimensions | No — categorical only |
| **Sprint contracts** | Opus 4.6 doesn't need them | Skipped entirely | Has task breakdown but optional |
| **Context isolation** | No longer needed with Opus 4.6 | Monolithic sessions | Session-per-task (legacy approach) |
| **Detailed task sharding** | Dead weight with capable models | None — agent drives exploration | Present via beads issues |

---

## The Real Difference

**Dark Factory** is built for the Opus 4.5/4.6 era — trust the model, give it high-level intent, let it explore and implement, then score the output adversarially. It's a bet on model capability.

**Spec-Workflow** is built for **decision quality** — force thorough thinking upfront, externalize design decisions in durable artifacts, implement incrementally with human judgment at every step. It's a bet on human oversight.

The Anthropic findings suggest dark-factory's approach is more aligned with where capable models are heading. But spec-workflow's interview process catches something dark-factory doesn't: it forces you to think about *what you actually want* before spending compute. Dark-factory's 3-sentence intent document may not surface edge cases that a 30-minute spec interview would catch.

---

## What Each Could Adopt

### Dark Factory could adopt from Spec-Workflow

- **Interview-driven intent clarification** — not the full spec, but a few probing questions before implementation to surface unstated assumptions and edge cases.
- **Spec-analyzer review** — automated quality check on the intent document before sending it to the Opus agent.

### Spec-Workflow could adopt from Dark Factory

- **Graded evaluation scoring** — replace pass/fail cold-review with 0-10 dimension-specific rubrics and borderline detection.
- **Monolithic Opus sessions** — drop session-per-task isolation in favor of single-session feature implementation, leveraging Opus 4.6's context resilience.
- **Automated pipeline execution** — reduce manual handoff overhead for high-confidence changes.

---

## Pipeline Architecture Comparison

### Dark Factory (3-phase, automated)

```
Input (Jira/file/inline)
  → Intent clarification (Sonnet, JSON output)
    → [OPTIONAL GATE] Human approval
      → Implementation (Opus, 30 turns, isolated worktree)
        → Test verification (auto-fix on failure)
          → Evaluation (Sonnet, scored JSON report)
            → [OPTIONAL GATE] Human approval with borderline detection
              → Complete
```

### Spec-Workflow (multi-step, human-driven)

```
/ideate → freeform exploration
  → /spec-create → deep interview → OpenSpec artifacts
    → /spec-to-issues → beads epic with child issues
      → /implement (per issue) → code + tests + commit
        → /cold-review → diff review in forked context
          → Manual PR creation
```

---

## Key Takeaway

Anthropic's harness research validates dark-factory's minimalist, trust-the-model approach for capable models. But spec-workflow's emphasis on pre-implementation thinking remains valuable — the question is whether that thinking should be encoded in detailed artifacts (spec-workflow) or left to the model's judgment (dark-factory). The answer likely depends on the stakes: low-risk features can trust the model; high-stakes changes benefit from externalized reasoning.
