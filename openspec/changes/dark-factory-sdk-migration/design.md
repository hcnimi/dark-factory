## Context

`/dark-factory` is a 760-line markdown slash command that orchestrates an 11-phase spec-to-PR pipeline. It works — 75% clean PR rate across 8 field runs — but the LLM mediates every operation including arg parsing, git commands, and CLI calls. This wastes ~50-60% of tokens on deterministic work and prevents code-level safety enforcement, observability, and cross-run learning.

The `claude-code-sdk` (Python, v0.0.25+) now provides programmatic control over Claude's agent loop with typed results, cost tracking, tool guards, and session management. This makes a "code controls LLM" architecture practical — Python owns the state machine, the LLM is called only for the 7-9 steps requiring intelligence.

**Constraints:**
- The CLI interface (`/dark-factory <source> [--dry-run] [--resume]`) must not change
- Worktree isolation (validated by 4 concurrent DPPT-* PRs) must be preserved
- The human checkpoint (Phase 5) remains mandatory
- Migration must be incremental — the pipeline can't go dark during development

## Goals / Non-Goals

**Goals:**
- Move all deterministic operations to Python (phases 0, 1, 2a, 5, 6, 10, 11)
- Use `claude-code-sdk` for LLM calls with `max_turns`, `allowed_tools`, `can_use_tool`
- Add per-phase timing and cost tracking
- Fix CI blindness via deterministic pre-fetch of CI config, test infra, conventions
- Replace prompt-based safety with `can_use_tool` security policy callback
- Tier models by task (sonnet for review/exploration, opus for implementation/spec)
- JSON state management with resume support

**Non-Goals:**
- Holdout test scenarios (StrongDM pattern) — future work after pipeline is stable
- GitHub Action for PR review feedback loop — depends on reliable pipeline first
- In-process MCP tools — adds complexity without clear payoff yet
- Headless mode (`claude -p` stage split) — evaluate after SDK migration validates
- Digital twin / devbox isolation — enterprise-scale concern, worktrees work at current scale

## Decisions

### 1. Incremental extraction, not big-bang rewrite

**Decision**: Migrate in 4 steps, each independently deployable. The markdown command delegates to Python for completed phases and handles the rest itself during transition.

**Why not big-bang**: The v2 Python state machine attempt (March 1-2) was architecturally sound but the maintenance burden killed it in 2 days. Incremental extraction lets each step be validated against real runs before proceeding.

**Alternatives considered:**
- Full rewrite to Python CLI tool → high risk, can't validate incrementally
- Keep markdown, add Python helpers → doesn't solve the core problem (LLM still mediates everything)

### 2. `claude-code-sdk` over `claude -p` subprocess

**Decision**: Use the Python SDK (`claude-code-sdk`) for all LLM calls, not `claude -p` subprocesses.

**Why**: SDK provides typed responses (`ResultMessage` with `total_cost_usd`, `duration_ms`, `num_turns`), `can_use_tool` callbacks, `interrupt()` for runaway agents, and native session management. Subprocesses give you stdout text and exit codes.

**Alternatives considered:**
- `claude -p` with `--output-format json` → gets structured output but no runtime tool guards, no interrupt, no cost tracking
- Direct Anthropic API → loses Claude Code's tool infrastructure (Read, Edit, Glob, Grep, Bash)

### 3. JSON state over markdown progress file

**Decision**: Pipeline state is a Python `dataclass` serialized to `.dark-factory/<KEY>.json`. The LLM never reads or writes it — the orchestrator owns state transitions.

**Why**: Anthropic's harness research: "the model is less likely to inappropriately change or overwrite JSON files." More importantly, when code owns the state, the LLM can't accidentally corrupt phase tracking.

### 4. Model tiering by phase

**Decision**: Use sonnet for bounded analytical tasks, opus for creative/implementation tasks.

| Phase | Task | Model | Rationale |
|-------|------|-------|-----------|
| 1 (inline) | Interview from description | sonnet | Structured Q&A |
| 2b | Codebase exploration | sonnet | Read-only analysis |
| 3 | Spec generation | opus | Creative synthesis |
| 4 | Plan review | sonnet | Checklist evaluation |
| 7 | Implementation | opus | Code generation |
| 8 | Test failure fix | opus | Debugging |
| 9 | Code review | sonnet | Diff analysis |
| 11 | PR body | sonnet | Summarization |

**Why not all opus**: Switching 4 of 8 calls to sonnet saves ~30-40% of sub-agent token cost with no quality loss on bounded tasks.

### 5. Security policy via `can_use_tool` callback

**Decision**: Define a `SecurityPolicy` dataclass evaluated by the `can_use_tool` callback on every tool invocation. Replaces prompt-based "do NOT" instructions.

```python
@dataclass
class SecurityPolicy:
    blocked_patterns: list[str]     # regex patterns for Bash commands
    write_boundary: Path            # no file writes outside this path
    blocked_tools: list[str]        # tool name patterns to deny
```

**Why**: Prompts provide guidance the LLM can ignore under pressure (failing tests, complex debugging). Code-level guards are deterministic — a blocked command stays blocked regardless of context window pressure.

### 6. Deterministic pre-fetch before LLM exploration

**Decision**: Phase 2 splits into 2a (Python, no LLM) and 2b (SDK call with pre-fetched context). Phase 2a collects: repo structure, package metadata, CI config, test infrastructure, convention files, recent git history.

**Why**: SDLC-3019 failed because the LLM never examined CI configuration. Pre-fetch guarantees CI config is always inspected. Also eliminates redundant exploration — 8 field runs each spent tokens rediscovering the same repo basics.

### 7. File layout

```
commands/dark-factory.md          # thin launcher (~50 lines, calls dark_factory.py)
dark_factory/
├── __init__.py
├── cli.py                        # arg parsing, input routing (Phase 0)
├── pipeline.py                   # main orchestration loop, phase runner
├── state.py                      # PipelineState dataclass, JSON serialization
├── ingest.py                     # Phase 1: Jira/file/inline ingestion
├── explore.py                    # Phase 2a prefetch + 2b SDK exploration call
├── scaffold.py                   # Phase 3: branch, worktree, deps, openspec
├── agents.py                     # SDK call wrappers (review, implement, fix)
├── security.py                   # SecurityPolicy, can_use_tool callback
├── verify.py                     # Phase 8: test detection, autofix, execution
└── pr.py                         # Phase 11: push, PR create, cleanup
```

**Why a package over a single file**: The evolution doc estimated ~300 lines for a single `dark_factory.py`. With typed state, security policy, pre-fetch logic, and SDK wrappers, a single file would reach 500+ lines. A package keeps each concern focused while maintaining the "code controls LLM" principle.

## Risks / Trade-offs

**[SDK stability]** `claude-code-sdk` is v0.0.25 — pre-1.0 API surface may change.
→ Mitigation: Pin version. SDK wraps Claude Code CLI which is stable. API surface is small (`query()`, `ClaudeSDKClient`, `ClaudeCodeOptions`).

**[Two runtimes]** During incremental migration (Steps 1-3), the pipeline runs partly in markdown, partly in Python. Debugging spans two execution contexts.
→ Mitigation: Each step is a clean boundary — completed phases are fully in Python, remaining phases are fully in markdown. No phase is split across runtimes.

**[Lost markdown simplicity]** The current command is readable by anyone who understands markdown. Python adds a code maintenance burden.
→ Mitigation: The v2 rewrite failed from over-engineering (typed state transitions, event bus). This design keeps Python functions simple — each phase is a function that takes inputs and returns outputs. The markdown command took 3 architecture iterations to get right; the Python code should inherit those learnings, not re-invent.

**[Python dependency in Claude Code environment]** Python 3.10+ must be available. Most dev environments have it, but it's a new requirement.
→ Mitigation: `claude-code-sdk` already requires Python. If they're running dark-factory, they have Claude Code, which ships with Python support.

**[Phase 5 interaction model]** The human checkpoint currently uses `AskUserQuestion` within the Claude Code session. The Python orchestrator needs to surface this interaction.
→ Mitigation: Phase 5 stays in the markdown launcher during Steps 1-3. In Step 4, the orchestrator uses the SDK's conversation capability or falls back to terminal input.

## Migration Plan

### Step 1: Deterministic phases (1-2 days)
Extract Phases 0, 5, 6, 10 to `dark_factory/`. The markdown command calls `python3 -m dark_factory phase0 "$ARGUMENTS"` and reads structured JSON output. Add JSON state file and phase timing.

### Step 2: Ingestion + pre-fetch (2-3 days)
Move Phase 1 and Phase 2a to Python. The pre-fetch function builds a context bundle (repo structure, CI config, test infra, conventions). Phase 2b remains an SDK call that receives the bundle.

### Step 3: SDK orchestration loop (1 week)
Move Phases 7, 8, 9, 11 to SDK calls. Wire up `can_use_tool`, `max_turns`, `allowed_tools`, model tiering. The markdown command now only handles Phases 3, 4, 5 (spec generation, plan review, human checkpoint).

### Step 4: Full orchestrator (1-2 weeks)
Move remaining phases. Markdown command becomes thin launcher. All 7-9 LLM calls go through the SDK. Add diff-size guard, autofix-before-LLM, dependency audit.

**Rollback**: At any step, reverting the markdown command to the previous version restores the prior behavior. No shared state between old and new — JSON state files are a new artifact.

## Open Questions

1. **Phase 5 in full-orchestrator mode**: Should the human checkpoint use SDK conversation, terminal `input()`, or a separate approval mechanism (e.g., file-based approval)?
2. **Parallel implementation agents**: The current pipeline launches `[P]` tasks concurrently. Should the SDK orchestrator use `asyncio.gather()` for parallel issues, or keep sequential execution for simpler debugging?
3. **Auto-memory integration**: Should the orchestrator write to Claude Code's memory system after Phase 8 and 11, or is that a Step 5 concern?
