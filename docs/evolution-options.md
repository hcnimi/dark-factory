# Dark Factory Evolution: Code Controls LLM

Evolution plan for `/dark-factory` — from LLM-interpreted markdown to a deterministic Python pipeline that calls the LLM only when intelligence is required. Validated against Stripe Minions, StrongDM Software Factory, and Claude Code SDK.

**Date**: 2026-02-27 (original) · 2026-03-09 (field data) · 2026-03-14 (restructured around deterministic pipeline)
**Scope**: `/dark-factory` command (`commands/dark-factory.md`) → `dark_factory.py` migration
**Current state**: 760-line slash command, 11-phase pipeline with worktree isolation, Level 3.5 autonomy
**Target state**: ~300-line Python orchestrator, 7-9 focused LLM calls, ~50-60% token savings
**Field runs**: 8 executions against `~/git/mq/sdlc/backstage` (see [Section 2.5](#25-field-results-8-runs-on-backstage))

**See also**: [dark-factory-next-improvements.md](dark-factory-next-improvements.md) — prioritized improvements from landscape evaluation (March 2026)

---

## Table of Contents

1. [Autonomy Landscape](#1-autonomy-landscape)
2. [Competitive Positioning](#2-competitive-positioning)
   - 2.5 [Field Results: 8 Runs on Backstage](#25-field-results-8-runs-on-backstage)
3. [Current Strengths](#3-current-strengths)
4. [Claude Code Features Not Yet Used](#4-claude-code-features-not-yet-used)
5. [Industry Best Practice Gaps](#5-industry-best-practice-gaps)
6. [Phase-by-Phase Determinism Analysis](#6-phase-by-phase-determinism-analysis)
7. [Target Architecture: Python Orchestrator](#7-target-architecture-python-orchestrator)
8. [Recommended Evolution Path](#8-recommended-evolution-path)
9. [Sources](#9-sources)

---

## 1. Autonomy Landscape

Dan Shapiro's "Five Levels of Coding Agents" framework (January 2026) — adapted from NHTSA's vehicle automation scale — provides the reference taxonomy:

| Level | Name | Human Role | Examples |
|-------|------|-----------|----------|
| 0 | Manual | Writes all code | Stack Overflow era |
| 1 | Assisted | Primary developer | Copilot autocomplete |
| 2 | Paired | Paired developer | Aider, Cursor inline |
| 3 | Supervised | Code reviewer | Devin, Amazon Q, GitHub Copilot Agent |
| 4 | Autonomous | Product manager | Factory AI Droids, Open SWE |
| 5 | Dark Factory | Specification owner | StrongDM Software Factory |

**`/dark-factory` operates at Level 3.5** — the agent explores, plans, implements, and reviews autonomously, but humans retain two mandatory checkpoints (plan approval + local dev verification).

### StrongDM Software Factory (Level 5 Reference)

StrongDM (3-person team, working since July 2025) established two charter rules: "Code must not be written by humans" and "Code must not be reviewed by humans."

Key architectural innovations:

| Innovation | What It Does |
|-----------|-------------|
| **Attractor** (graph pipeline) | DAG of execution nodes with NL edges, checkpoint after every node |
| **Digital Twin Universe** | Behavioral clones of 6 SaaS APIs (Okta, Jira, Slack, etc.) for testing |
| **Holdout Scenarios** | End-to-end tests hidden from the coding agent (ML train/test separation) |
| **Satisfaction Metric** | Probabilistic pass rate (3 runs, 2/3 threshold, 90% gate) |
| **CXDB** | Immutable DAG-based context store (16k Rust + 9.5k Go + 6.7k TS) |
| **NLSpec** | Natural language specifications as the control plane |

Critical insight: generated code is treated as "opaque weights" — validated through behavioral observation, never through human inspection.

---

## 2. Competitive Positioning

| System | Level | Ticket→PR | Holdout Tests | Review Model | Resume |
|--------|-------|-----------|---------------|-------------|--------|
| **`/dark-factory`** | 3.5 | Jira → OpenSpec → Beads → PR | No | Dual AI gates + human | Yes (progress file) |
| StrongDM Factory | 5 | Spec-driven, no tickets | Yes (hidden scenarios) | None (opaque weights) | Yes (Attractor checkpoints) |
| Devin | 3 | Jira/Slack → sandbox → PR | No | Human review required | Limited |
| GitHub Copilot Agent | 3 | Issue → Actions env → draft PR | No | Human review required | No |
| Cursor Cloud Agents | 3 | IDE-initiated → worktree → PR | No | BugBot + human | No |
| Factory AI Droids | 4 | Issue → org context → PR | No | Human review | Limited |
| Open SWE | 3-4 | Manager → Planner → Programmer → Reviewer | No | AI reviewer sub-agent | LangGraph state |
| Amazon Q | 3 | NL description → plan → code | No | Human approves plan | No |

### Where `/dark-factory` Leads

- **Dual review gates** (plan review Phase 4 + implementation review Phase 9) — most pipelines have zero or one
- **Sub-agent isolation per issue** — mirrors Spotify's finding that context pollution is a primary failure mode
- **Tiered test verification** (lint → co-located → full suite) — only Amazon Q does something comparable
- **Progress file with resumability** — more robust than most competitors (branch fallback + progress file + fresh start detection)
- **Explicit scope constraints** in implementation prompts — addresses Martin Fowler's documented #1 agent failure mode ("overeagerness")
- **Graceful degradation** — non-critical failures (review sub-agent dies) don't halt the pipeline

---

## 2.5 Field Results: 8 Runs on Backstage

Between February and March 2026, `/dark-factory` was executed 8 times against `~/git/mq/sdlc/backstage` (a Backstage developer portal). Results provide the first empirical data on pipeline reliability.

### Execution Summary

| # | Jira | PR | Outcome | Size | CI | Notes |
|---|------|----|---------|------|----|-------|
| 1 | SDLC-2888 | — | **No PR** | 8 commits | ? | Pipeline died before PR creation; no crash log |
| 2 | SDLC-3019 | #518 | **Closed** | +1704/-11 | Fail | SonarQube critical violation + `secrets.json` missing in CodeBuild |
| 3 | SDLC-3123 | #554 | **Merged** | +2948/-12 | Pass | ADR plugin integration — clean approval |
| 4 | SDLC-3198 | #568 | **Merged** | +1353/-10 | Pass | ADR service bootstrap template — 97.2% coverage |
| 5 | DPPT-41 | #599 | Open | +69/-0 | Pass | Service links — tightly scoped |
| 6 | DPPT-42 | #600 | Open | +185/-0 | Pass | AWS CodePipeline/CodeBuild plugins |
| 7 | DPPT-43 | #602 | Open | +263/-29 | Pass | Datadog service health plugin |
| 8 | DPPT-44 | #601 | Open | +307/-36 | Pass | Remove non-functioning widgets |

**Success rate**: 6/8 (75%) produced clean PRs that passed CI. 2/8 merged. 4 DPPT-* PRs created in a single parallel batch (~1 hour) using worktree isolation — all passed CI independently.

### What Worked

1. **Consistent output quality**: Every branch follows the same commit structure — `checkpoint(openspec)` → implementation → `checkpoint: address review feedback`. PR descriptions include summary, test plan, Jira link, and OpenSpec reference. Human reviewers approved quickly.

2. **Backstage plugin integration is the sweet spot**: Bounded tasks — adding plugins, `EntitySwitch.Case` conditional rendering, annotation-based guards — play to LLM coding strengths. Pattern-following work with clear boundaries.

3. **Worktree isolation enables batch execution**: The 4 DPPT-* PRs prove that concurrent runs against the same repo work. All touched `EntityPage.tsx` but in non-overlapping ways.

4. **Self-review catches real issues**: Dual review gates produce "address review feedback" commits in every run — the pipeline iterates on its own code before presenting to humans.

5. **CI compliance is strong**: 6/7 PRs passed SonarQube, Snyk (security + license), and Blackbird CI. Zero security findings across all PRs.

6. **Tests included with good coverage**: PRs #554, #568, #518 included unit tests. PR #568 achieved 97.2% coverage on new code. PR #601 had 8 tests at 100% coverage for new utility functions.

### What Failed

1. **CI environment blindness (SDLC-3019)**: The one closed PR added `$include` directives referencing `secrets.json` — a file that exists locally but not in CodeBuild. Phase 2 codebase exploration doesn't inspect CI configuration or understand build-time constraints. **Root cause**: No CI-aware exploration step.

2. **Silent pipeline death (SDLC-2888)**: 8 commits on the branch (complete with spec, scaffolding, tests, review feedback) but no PR was ever created. No crash log, no event trail, no progress file artifact to diagnose. **Root cause**: No observability/event logging.

3. **No cross-run learning**: Each run rediscovers that Backstage uses `EntitySwitch.Case`, that `app-config.local.yaml` can't reference local-only files, that tests are `*.test.tsx` with Jest. **Root cause**: No auto-memory between runs.

4. **Documentation drift in specs**: PR #599's Polynator review caught that the spec said `spec.links` but implementation correctly used `metadata.links`. OpenSpec scenarios can contain inaccurate implementation details. **Root cause**: Spec generation in Phase 3 can hallucinate API details.

### Review Feedback Patterns

- **Polynator AI reviews** found 0-3 issues per PR. Common: annotation key mismatches, relation type coverage, sync I/O in Node.js.
- **Human reviewers** approved quickly with minimal substantive comments. PR #568 went through multiple dismiss/re-request cycles but the feedback was lightweight.
- **Review cycle time** is dominated by human availability, not code quality.

### Key Metrics

| Metric | Value |
|--------|-------|
| Clean PR rate | 75% (6/8) |
| Merge rate | 25% (2/8) — 4 awaiting review |
| CI pass rate (of PRs created) | 86% (6/7) |
| Batch parallelism | 4 concurrent PRs, all passed |
| Failure modes | CI awareness (1), silent death (1) |

---

## 3. Current Strengths

Features already aligned with 2026 best practices (Anthropic, Spotify, Martin Fowler/ThoughtWorks research):

| Pattern | Implementation | Source Alignment |
|---------|---------------|-----------------|
| Sequential state machine with checkpoints | 11 explicit phases, progress file | Anthropic: "make agents behave like dependable software" |
| Mandatory human checkpoint before implementation | Phase 5 AskUserQuestion | Single most important safety gate (universal consensus) |
| Isolated sub-agents per issue | Task tool, one agent per beads issue | Spotify: context pollution is primary failure mode |
| Dual review gates | Phase 4 (plan) + Phase 9 (implementation) | Exceeds most production pipelines |
| Retry budgets with hard stops | Max 2 test retries, max 1 review cycle | Prevents infinite loops and cost runaway |
| Branch preservation on fatal error | Progress file left in place for `--resume` | Enables manual recovery |
| Git worktree isolation | Each run gets its own worktree; main repo untouched | Enables concurrent runs (validated by 4 parallel DPPT-* PRs) |

### Architectural Evolution Note

The pipeline went through three architectures in two weeks:
1. **v1 (Feb 26)**: 555-line slash command — worked but monolithic
2. **v2 (Mar 1-2)**: Python state machine with `claude -p` subprocesses — architecturally sound (typed transitions, event logging, true process isolation) but higher maintenance burden
3. **v3 (Mar 9)**: 603-line slash command with Task tool + worktree isolation — combines v1's maintainability with v2's isolation goals

The Python POC's **observability patterns** (event logging, phase timing, typed state) remain the biggest gap in v3. The runtime pivot was justified — the markdown command is more maintainable and leverages Claude Code's native orchestration — but the lost instrumentation should be backported (see Phase B recommendations).

---

## 4. Claude Code Features Not Yet Used

### P0 — Immediate Wins (2-3 line changes each)

#### 4.1 `model` Parameter on Task Tool

**What it does**: Selects the model for a sub-agent (`"haiku"`, `"sonnet"`, `"opus"`). Each sub-agent can use a different model independently of the parent conversation.

**Current state**: All sub-agents inherit the parent model (opus). Plan review, code review, and implementation all consume opus tokens.

**Recommendation**: Tier model usage by task complexity.

| Phase | Sub-agent | Current | Recommended | Rationale |
|-------|-----------|---------|-------------|-----------|
| 4 | Plan review | opus | `sonnet` | Structured checklist evaluation against acceptance criteria |
| 7 | Implementation | opus | `opus` | Strongest coding capability needed |
| 9 | Code review | opus | `sonnet` | Diff review against spec — well-scoped, mechanical |

**Implementation sketch** (Phase 4):
```
Task(
  subagent_type: "code-reviewer",
  model: "sonnet",
  prompt: "Review the following development plan..."
)
```

**Cost impact**: Switching 2 of 5 typical sub-agents to sonnet saves ~30-40% of total sub-agent token cost.

---

#### 4.2 `max_turns` Parameter on Task Tool

**What it does**: Limits the number of agentic turns (API round-trips) before the sub-agent stops. Prevents runaway execution and provides an implicit cost cap.

**Current state**: No turn limits. A stuck implementation sub-agent could loop until context exhaustion.

**Recommendation**:

| Sub-agent | `max_turns` | Rationale |
|-----------|-------------|-----------|
| Plan review (Phase 4) | 10 | Read files + produce structured review |
| Implementation (Phase 7) | 30 | Explore → implement → self-review → test → commit |
| Code review (Phase 9) | 10 | Read diff + produce structured review |

**Implementation sketch** (Phase 7):
```
Task(
  subagent_type: "general-purpose",
  max_turns: 30,
  prompt: "You are implementing a beads issue..."
)
```

---

### P1 — High Impact (requires modest command changes)

#### 4.3 `isolation: "worktree"` on Task Tool — ✅ IMPLEMENTED (PR #5, 2026-03-09)

**What it does**: Creates a temporary git worktree — a separate working directory on a new branch based on HEAD. The sub-agent works in complete filesystem isolation. If changes are made, the worktree path and branch are returned. If no changes, auto-cleaned.

**Implementation**: The entire dark-factory run now creates a worktree at `${REPO_ROOT}/../${REPO_BASENAME}-df-$(jira-key-lowercase)`. This enables multiple concurrent runs against the same repo without branch conflicts. The main repo is never checked out to a different branch.

**Field validation**: The 4 DPPT-* PRs (#599, #600, #601, #602) were created in parallel within ~1 hour, all targeting the same backstage repo. All passed CI independently despite touching overlapping files (`EntityPage.tsx`).

---

#### 4.4 Hooks for Deterministic Safety Enforcement

**What it does**: Shell commands that run at specific points in Claude Code's lifecycle. `PreToolUse` hooks fire before a tool executes. Exit code 2 = block the action. Hooks are deterministic (no LLM involved).

**Current state**: Safety relies entirely on prompt instructions ("Do NOT modify files unrelated to your issue"). LLMs can be persuaded to ignore "Do NOT" instructions, especially under pressure from failing tests.

**Recommendation**: Add a `PreToolUse` hook to block dangerous operations.

**Implementation** — new file `.claude/settings.json` (project-level):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'INPUT=$(cat); CMD=$(echo \"$INPUT\" | jq -r \".tool_input.command\"); if echo \"$CMD\" | grep -qE \"(rm -rf /|git push.*--force|DROP TABLE|git checkout main)\"; then echo \"dark-factory: blocked dangerous command\" >&2; exit 2; fi; exit 0'"
          }
        ]
      }
    ]
  }
}
```

Blocked operations:
- `rm -rf /` — catastrophic delete
- `git push --force` — history destruction
- `git checkout main` — sub-agent escaping its branch
- `DROP TABLE` — destructive SQL

**Defense-in-depth**: Prompts provide guidance. Hooks provide enforcement.

---

#### 4.5 Auto Memory for Cross-Run Learning

**What it does**: Persistent memory at `~/.claude/projects/<project>/memory/MEMORY.md`. First 200 lines load automatically at every session start. Survives across sessions and pipeline runs.

**Current state**: Each `/dark-factory` run starts cold. Learnings like "this repo's tests take 4 minutes" or "selective tests pass 70% faster with `-x` flag" are rediscovered every run.

**Recommendation**: Add memory-save instructions to Phase 8 and Phase 11.

After Phase 8 (Test Verification):
```
Save to memory: test command used, whether selective tests worked,
total test duration, any flaky tests encountered, linter flags needed.
```

After Phase 11 (PR Creation):
```
Save to memory: total pipeline duration by phase, which phases were
slowest, repo-specific patterns worth remembering.
```

Future runs automatically load this at session start, enabling Phase 2 (Codebase Exploration) to leverage prior knowledge.

---

### P2 — Medium Impact (architectural considerations)

#### 4.6 `run_in_background: true` on Task Tool

**What it does**: Launches a sub-agent in the background. You get notified when it completes. Enables concurrent work in the parent context while sub-agents execute.

**Current state**: All sub-agents block. Parallel `[P]` tasks are launched as concurrent foreground calls.

**Recommendation**: Evaluate for Phase 7 parallel tasks. Background agents allow the orchestrator to update the progress file or prepare the next sequential task while `[P]` agents run. However, the current foreground approach already supports concurrent Task calls, so the incremental benefit is modest.

**When it becomes compelling**: If orchestration needs to do meaningful work between spawning agents and collecting results.

---

#### 4.7 Headless Mode (`-p` flag) + Permission Pre-Configuration

**What it does**: `claude -p` runs non-interactively (no terminal UI). Combined with `--allowedTools` and `--default-mode acceptEdits`, enables fully unattended execution.

**Current state**: `/dark-factory` runs interactively throughout. Phase 5 requires human approval, but Phases 6-11 are fully autonomous.

**Recommendation**: Consider splitting into two stages:

1. **Stage 1 (interactive)**: Phases 0-5 via normal `/dark-factory`
2. **Stage 2 (headless)**: After human approval, spawn:
   ```bash
   claude -p "Resume dark-factory for <JIRA-KEY> from Phase 6" \
     --allowedTools "Bash(git *),Bash(bd *),Bash(npm *),Read,Edit,Glob,Grep,Task" \
     --default-mode acceptEdits \
     --max-turns 50
   ```

This lets the developer walk away after plan approval. The pipeline runs unattended through implementation, testing, review, and PR creation.

**Tradeoff**: Loses the Phase 10 local dev verification (interactive). Could be replaced with a post-PR smoke test or deferred to PR review.

---

#### 4.8 GitHub Action (`claude-code-action`) for Post-PR Feedback Loop

**What it does**: Official GitHub Action that triggers Claude on PR/issue events. Responds to `@claude` mentions in PR comments. Can run custom prompts and slash commands.

**Current state**: `/dark-factory` ends at Phase 11 (PR creation). PR review comments require manual handling.

**Recommendation**: Use as a "Phase 12" — PR review feedback loop:
```yaml
# .github/workflows/dark-factory-feedback.yml
name: Dark Factory PR Feedback
on:
  pull_request_review_comment:
    types: [created]
jobs:
  respond:
    if: contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          claude_args: "--max-turns 10 --model claude-sonnet-4-6"
```

Reviewers comment `@claude fix this` on a dark-factory PR, and Claude applies the fix and pushes a commit.

---

### P3 — Target Architecture: Claude Code SDK

#### 4.9 Claude Code SDK Migration

**What it is**: Python (`claude-code-sdk`, v0.0.25+) and TypeScript (`@anthropic-ai/claude-code`, v2.1.76+) SDKs that provide programmatic control over Claude's agent loop. Same tools as Claude Code, but orchestrated by your code instead of a markdown prompt.

> **Note**: The SDK package is `claude-code-sdk` (not `claude-agent-sdk`). The options class is `ClaudeCodeOptions` (not `ClaudeAgentOptions`).

**What it offers over the current command**:

| Capability | Current (Markdown) | Claude Code SDK |
|-----------|-------------------|-----------|
| State machine | Implicit (Claude follows instructions) | Explicit Python/TS code |
| Retry logic | Prompt-based ("max 2 retries") | Your code wraps `query()` with retry logic |
| Error handling | Prompt-based ("if tests fail, stop") | `try/except` with typed errors (`ProcessError`, `CLIConnectionError`, etc.) |
| Session management | Progress file | Native `session_id` with `resume` parameter |
| Hooks | Shell commands (settings.json) | Native async Python callbacks per event |
| Output format | Unstructured text | Typed message stream (`AssistantMessage`, `ResultMessage`, `ToolUseBlock`, etc.) |
| Tool control | Prompt-based ("do NOT use X") | `allowed_tools` + runtime `can_use_tool` callback |
| Agent control | Hope it stays on task | `interrupt()` to abort runaway agents |
| Custom tools | MCP servers via config | In-process MCP via `@tool` decorator (zero IPC) |
| Observability | No timing/cost data | `ResultMessage.total_cost_usd`, `duration_ms`, `num_turns` per call |
| Testability | Manual testing only | Mock `Transport` interface; unit-test orchestration |

**Key capabilities for dark-factory**:

**1. `ClaudeSDKClient` — bidirectional mode with interrupt**

The simple `query()` is fire-and-forget. `ClaudeSDKClient` enables reactive control — the orchestrator can monitor agent behavior and abort if needed:

```python
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

async with ClaudeSDKClient(ClaudeCodeOptions(
    model="claude-opus-4-6",
    allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep"],
    permission_mode="acceptEdits",
    max_turns=30,
    cwd=worktree_path
)) as client:
    await client.connect()
    await client.query(f"Implement {issue.title}...")
    async for msg in client.receive_response():
        if is_off_rails(msg):  # custom guard
            await client.interrupt()
            break
```

**2. `can_use_tool` — dynamic per-call tool permissions**

More powerful than static `allowed_tools`. The orchestrator can make runtime decisions per tool call (e.g., block file writes outside the worktree):

```python
async def guard_tools(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "Edit" and not tool_input["file_path"].startswith(worktree_path):
        return False  # block writes outside worktree
    return True

options = ClaudeCodeOptions(can_use_tool=guard_tools)
```

**3. In-process MCP servers — custom tools in your Python process**

Define tools that run inside the orchestrator, with access to pipeline state:

```python
from claude_code_sdk import create_sdk_mcp_server, tool

@tool("save_progress", "Update pipeline progress file", {"phase": int, "status": str})
async def save_progress(args):
    progress.update(phase=args["phase"], status=args["status"])
    progress.write()
    return {"content": [{"type": "text", "text": "Progress saved"}]}

server = create_sdk_mcp_server("pipeline-tools", tools=[save_progress])
options = ClaudeCodeOptions(mcp_servers={"pipeline": server})
```

**4. Built-in observability**

Every `ResultMessage` includes cost and timing without external instrumentation:

```python
result_msg = ...  # final message from query()
print(f"Phase 7: ${result_msg.total_cost_usd:.4f}, "
      f"{result_msg.duration_ms/1000:.1f}s, "
      f"{result_msg.num_turns} turns")
```

**Full `ClaudeCodeOptions` surface** (relevant fields):

| Field | Type | Dark Factory Use |
|-------|------|-----------------|
| `allowed_tools` | `list[str]` | Restrict per sub-agent type |
| `disallowed_tools` | `list[str]` | Block specific tools |
| `model` | `str` | Tier by phase (sonnet for review, opus for impl) |
| `permission_mode` | `"default" \| "acceptEdits" \| "bypassPermissions"` | Unattended execution |
| `max_turns` | `int` | Cost cap per phase |
| `system_prompt` | `str` | Clean per-phase injection |
| `append_system_prompt` | `str` | Add to default system prompt |
| `mcp_servers` | `dict \| Path` | Custom + external tools |
| `resume` | `str` | Resume by session ID |
| `cwd` | `Path` | Point each agent at the worktree |
| `can_use_tool` | `async callback` | Runtime tool guard |
| `hooks` | `dict[HookEvent, ...]` | Python callbacks for PreToolUse, Stop, etc. |
| `env` | `dict[str, str]` | Different env vars per agent |
| `add_dirs` | `list[Path]` | Multi-directory context |

**When to migrate**: The SDK is the natural target for the "code controls LLM" architecture. The markdown command works but burns tokens on orchestration the LLM doesn't need to do. Migration is justified when pipeline reliability and cost matter — not a future aspiration but the next step. See [Section 7](#7-target-architecture-python-orchestrator) for the concrete architecture.

---

## 5. Industry Best Practice Gaps

Gaps identified from Anthropic, Spotify, Martin Fowler/ThoughtWorks, and StrongDM research that are independent of Claude Code features:

### 5.1 Holdout Testing (Highest Architectural Priority)

**The gap**: OpenSpec Gherkin scenarios are visible to the implementing agent. The agent can (consciously or not) tailor its implementation to pass those specific scenarios without truly satisfying the intent.

**The pattern**: StrongDM's holdout approach applies ML's train/test separation to code generation:
1. Humans write behavioral scenarios stored outside the codebase
2. The coding agent never sees these scenarios
3. A separate validation agent runs scenarios 3x with a 2/3 pass threshold
4. Overall gate: 90% scenario passage rate required

**Recommendation**: Split scenarios into **spec scenarios** (visible to implementer, used for guidance) and **holdout scenarios** (hidden, evaluated in Phase 8 by a separate validation agent with no implementation context).

### 5.2 Deterministic Context Pre-Fetching (Stripe Minions Pattern)

**The gap**: Phase 2 (Codebase Exploration) is entirely LLM-driven — the agent decides what to look at. This burns tokens on open-ended exploration, produces inconsistent results across runs, and misses predictable context that every run needs.

**The pattern**: Stripe's minions separate context gathering into two stages:
1. **Deterministic pre-fetch (no LLM)**: Before the model wakes up, the orchestrator scans the trigger (Slack thread, Jira ticket) for links, pulls referenced tickets, searches code via Sourcegraph, and attaches scoped rule files (`.cursorrules`). This runs in milliseconds, costs zero tokens, and produces the same output every time.
2. **Agent exploration (LLM)**: The model receives the pre-fetched bundle and only explores what the deterministic step couldn't cover.

Their design principle (paraphrased): putting LLMs into contained boxes compounds into system-wide reliability — writing code to deterministically accomplish small decisions saves tokens and reduces error surface.

**Current impact**: Each of 8 field runs rediscovered the same Backstage patterns (`EntitySwitch.Case`, Jest `*.test.tsx`, `app-config.local.yaml` constraints). With pre-fetching, this context would be handed to the agent for free.

**Recommendation**: Split Phase 2 into **Phase 2a (deterministic)** and **Phase 2b (agent-driven)**. Phase 2a runs fixed commands and builds a context bundle; Phase 2b receives the bundle and explores gaps.

**Phase 2a: Deterministic Pre-Fetch** (new, no LLM):

```bash
# 1. Repo structure snapshot
ls -1 "$WORKTREE_PATH"                          # top-level dirs
find "$WORKTREE_PATH" -name "*.md" -maxdepth 2  # root docs

# 2. Project metadata
cat "$WORKTREE_PATH/package.json" 2>/dev/null | jq '{name, scripts, dependencies: (.dependencies | keys), devDependencies: (.devDependencies | keys)}'
cat "$WORKTREE_PATH/pyproject.toml" 2>/dev/null
cat "$WORKTREE_PATH/go.mod" 2>/dev/null

# 3. CI/CD configuration (addresses SDLC-3019 failure)
cat "$WORKTREE_PATH/blackbird.yaml" 2>/dev/null
cat "$WORKTREE_PATH/buildspec.yml" 2>/dev/null
cat "$WORKTREE_PATH/.github/workflows/"*.yml 2>/dev/null
cat "$WORKTREE_PATH/Dockerfile" 2>/dev/null

# 4. Test infrastructure
find "$WORKTREE_PATH" -name "jest.config*" -o -name "pytest.ini" -o -name "conftest.py" -o -name "vitest.config*" | head -5
# Extract test command from package.json scripts
cat "$WORKTREE_PATH/package.json" 2>/dev/null | jq '.scripts | to_entries[] | select(.key | test("test|lint|check")) | "\(.key): \(.value)"'

# 5. Target repo conventions
cat "$WORKTREE_PATH/CLAUDE.md" 2>/dev/null
cat "$WORKTREE_PATH/AGENTS.md" 2>/dev/null
cat "$WORKTREE_PATH/.cursorrules" 2>/dev/null

# 6. Recent changes (pattern detection)
git -C "$WORKTREE_PATH" log --oneline -20
git -C "$WORKTREE_PATH" log --diff-filter=A --name-only --format="" -10 | sort -u  # recently added files

# 7. Ticket-relevant code search (deterministic keyword extraction)
# Extract nouns/identifiers from <summary> and <acceptance-criteria>
# Search for matches in file names and content
grep -rl "<keyword>" "$WORKTREE_PATH/src" 2>/dev/null | head -20
```

Output: a structured **context bundle** (markdown or JSON) containing:
- Repo structure, language/framework, package manager
- CI configuration and environment constraints
- Test framework and test command
- Convention files (CLAUDE.md, .cursorrules)
- Recent git activity and relevant file paths

**Phase 2b: Agent Exploration** (existing, LLM-driven, but now receives the bundle):

The exploration agent receives the pre-fetched context bundle as input, reducing its scope to:
- Reading specific files identified by keyword search
- Understanding module boundaries and architecture
- Identifying patterns not captured by deterministic search
- Noting gotchas specific to the ticket's scope

**Cost impact**: Pre-fetching eliminates 30-50% of Phase 2 exploration tokens (estimated from 8 field runs where ~40% of exploration was rediscovering repo basics). Deterministic steps run in <5 seconds vs 30-60 seconds for LLM exploration.

**Reliability impact**: Every run gets the same baseline context regardless of LLM exploration quality. CI configuration is always inspected (would have prevented SDLC-3019). Convention files are never missed.

**Source**: [Stripe Engineering: Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2) — deterministic/agent node separation as a core architectural primitive.

---

### 5.3 Tool Subsetting for Sub-Agents (Stripe Minions Pattern)

**The gap**: Implementation and review sub-agents (Phases 4, 7, 9) receive access to every tool Claude Code offers. A backend implementation task gets Excalidraw MCP tools; a review sub-agent gets file-writing capabilities it shouldn't use.

**The pattern**: Stripe's Toolshed contains nearly 500 MCP tools, but each minion receives an intentionally small, curated subset relevant to its task type. As they put it: "Agents perform best when given a 'smaller box' with a tastefully curated set of tools." Curating the tool set per task type reduces the error surface and prevents the model from choosing inappropriate tools. Teams can also configure per-user tool customizations — additional thematically grouped tool sets that individual engineers enable for their minions.

**Current impact**: No observed failure from tool confusion in 8 field runs, but the risk grows as MCP servers proliferate. An implementation agent that discovers it can query Jira mid-task may go down a rabbit hole.

**Recommendation**: Define tool subsets per sub-agent type using the Task tool's capabilities.

| Sub-agent | Phase | Allowed Tools |
|-----------|-------|---------------|
| Plan review | 4 | `Read`, `Glob`, `Grep` |
| Implementation | 7 | `Read`, `Edit`, `Write`, `Bash`, `Glob`, `Grep` |
| Code review | 9 | `Read`, `Glob`, `Grep`, `Bash(git diff *)` |

**Implementation sketch** (Phase 4):
```
Spawn a code-reviewer sub-agent with:
- Only Read, Glob, Grep tools (no editing, no Bash beyond git)
- Prompt: "Review the following plan against acceptance criteria..."
```

**Benefit**: Prevents scope creep at the tool level. A review agent that can't edit files can't "helpfully" fix issues it finds — it must report them for the orchestrator to handle. This matches Stripe's principle that the *system* controls the model, not the other way around.

**Source**: [Stripe Engineering: Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2) — curated tool subsets as reliability lever.

---

### 5.4 Scoped Context Files (Stripe `.cursorrules` Pattern)

**The gap**: Phase 2 exploration produces findings that live in the agent's context window but are lost between runs. Each run rediscovers that Backstage uses `EntitySwitch.Case`, that tests are `*.test.tsx` with Jest, that `app-config.local.yaml` can't reference local-only files. Auto-memory (Section 4.5) addresses cross-run learning, but doesn't help within a run when sub-agents work in different directories.

**The pattern**: Stripe standardized on Cursor's rule format and syncs rules so that Cursor, Claude Code, and minions all read the same guidance files. Key insight: **format convergence** over format proliferation — one set of rules, multiple consumers. Rules are directory-scoped and **automatically attached to the agent's context as it traverses directories**. Rules are conditionally applied based on the subdirectory the agent is working in, preventing context window saturation from irrelevant rules.

**Recommendation**: Use existing `.cursorrules` or CLAUDE.md files in target repositories (not a new `.claude-context` format). When a Phase 7 sub-agent works in a directory, the orchestrator scans for and injects the nearest rule file from the directory or its ancestors. In the SDK architecture, this becomes a deterministic step — scan for rule files before spawning the agent, include them in `system_prompt`.

**Example** — `packages/backend/src/plugins/CLAUDE.md` (or `.cursorrules`):
```markdown
# Backstage Plugin Conventions

- Plugins register via `createRouter()` exported from `plugin.ts`
- Use `EntitySwitch.Case` for conditional rendering in `EntityPage.tsx`
- Test files: `*.test.tsx` alongside source, using Jest + React Testing Library
- Never reference `app-config.local.yaml` in code — use `app-config.yaml` with env var substitution
- CI runs in CodeBuild — no access to `secrets.json` or local-only config
```

**How it fits the SDK pipeline**:
- **Phase 2a (deterministic)**: `prefetch_context()` scans for CLAUDE.md and `.cursorrules` files in the worktree; includes them in the context bundle
- **Phase 7 (implementation)**: Orchestrator injects relevant rule files into `system_prompt` per sub-agent based on which directories the task touches
- **Phase 11 (post-run)**: Optionally, auto-generate or update rule files based on learnings (human-approved)

**Relationship to auto-memory**: Auto-memory (Section 4.5) stores learnings in `~/.claude/projects/<project>/memory/` and loads globally. Rule files live *in the repo* and apply *per-directory*. They serve different purposes:
- Auto-memory: "This repo's tests take 4 minutes" (operational knowledge)
- Rule files: "Plugins in this directory use `createRouter()`" (structural conventions)

**Source**: [Stripe Engineering: Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2) — scoped rule files as context management primitive.

---

### 5.5 Dependency Audit

**The gap**: No verification that AI-added dependencies actually exist. Research shows ~20% of AI-generated code recommends non-existent packages ("slopsquatting"), and 43% of hallucinated packages are repeated consistently — enabling supply chain attacks.

**Recommendation**: Add to Phase 8 test verification:
```bash
npm audit          # Node.js
pip-audit          # Python
go vet ./...       # Go
```

### 5.6 Security Scanning (SAST)

**The gap**: 25-30% of AI-generated code contains Common Weakness Enumerations (CWEs). Security degrades with each fix cycle (a 2025 research finding).

**Recommendation**: Add SAST to Phase 8 or Phase 9. Run on the diff, not the full codebase:
```bash
semgrep --config auto --diff <base-branch>..HEAD
```

### 5.7 Post-PR Jira Status Sync

**The gap**: After PR creation, the Jira ticket status is not updated. Bidirectional sync is incomplete.

**Recommendation**: Add to Phase 11 after PR creation:
```
mcp__claude_ai_Atlassian__transitionJiraIssue(
  issue_key="<jira-key>",
  transition_id="<in-review-transition>"
)
```

### 5.8 Diff-Size Gate

**The gap**: If implementation produces 10x the expected diff, something went wrong (scope creep, hallucination, brute-force fix). No guard exists.

**Recommendation**: Add between Phase 9 and Phase 10:
```bash
LINES_CHANGED=$(git diff --stat main | tail -1 | grep -oP '\d+ insertion' | grep -oP '\d+')
TASK_COUNT=$(grep -c '^\d' openspec/changes/<change-id>/tasks.md)
EXPECTED=$((TASK_COUNT * 150))  # ~150 lines per task heuristic
if [ "$LINES_CHANGED" -gt $((EXPECTED * 3)) ]; then
  echo "WARNING: Diff is ${LINES_CHANGED} lines (expected ~${EXPECTED}). Escalating."
fi
```

### 5.9 Phase Timing / Observability

**The gap**: No timing data in the progress file. No insight into which phases are slow or where cost concentrates.

**Recommendation**: Add timestamps to each phase transition in the progress file:
```markdown
## Completed Phases
- [x] Phase 0: Tool Discovery (12s)
- [x] Phase 1: Jira Ticket Ingestion (8s)
- [x] Phase 7: Implementation (14m 32s) ← bottleneck
```

### 5.10 Progress File Format

**The gap**: Progress file is Markdown. Anthropic's harness research recommends JSON — "the model is less likely to inappropriately change or overwrite JSON files."

**Recommendation**: In the SDK architecture, progress state is a Python dataclass serialized to `.dark-factory/<KEY>.json`. The LLM never reads or writes it — the orchestrator code owns state transitions. This eliminates the risk entirely.

### 5.11 Blueprints as First-Class DAG (Stripe Minions Pattern)

**The gap**: The document treats Stripe's patterns as individual techniques (pre-fetch, tool subsetting, rules). The overarching architectural innovation is the **blueprint** — a workflow DAG that mixes deterministic nodes and agent nodes as a first-class concept.

**The pattern**: Stripe's blueprints are extensible workflow definitions where each node is either deterministic code or an agent loop. Teams build custom blueprints for specialized tasks (migrations, API changes, test generation). Deterministic nodes include "run configured linters" and "push changes" — they don't invoke an LLM at all, they just run code.

**Relevance**: Dark-factory's 11-phase pipeline is implicitly a blueprint. Making it explicit (a Python DAG) enables: reusable node definitions, conditional phase skipping, parallel execution of independent nodes, and team-customizable workflows.

### 5.12 Devbox vs Worktree Isolation (Stripe Minions Pattern)

**The gap**: Dark-factory uses git worktrees for isolation. Stripe uses dedicated EC2 instances ("devboxes") pre-warmed in 10 seconds with full repo + services.

**Stripe's assessment**: "Containerization or git worktrees can help, but they're hard to combine and it's fundamentally difficult to build local agents that have all the power of a developer's shell but are appropriately constrained."

**Current position**: Worktrees are validated by 4 concurrent DPPT-* PRs and work well at dark-factory's scale (single repo, bounded tasks). Devboxes become relevant at enterprise scale with integration testing requirements. No action needed now, but acknowledge the tradeoff.

### 5.13 CI Autofix Integration (Stripe Minions Pattern)

**The gap**: When tests fail in Phase 8, dark-factory sends failures back to the LLM agent for analysis and fix. Stripe auto-applies fixes from tests that have known autofix rules — the LLM is never involved for deterministic fixes.

**Recommendation**: Before invoking the LLM for test failures, check if the test framework supports autofixes (e.g., `eslint --fix`, `black`, `isort`). Apply deterministic fixes first, re-run. Only escalate to LLM if failures remain after autofix.

### 5.14 Security Control Framework for MCP Tools (Stripe Minions Pattern)

**The gap**: Section 4.4 proposes a `PreToolUse` hook with regex matching for dangerous commands. Stripe uses a systematic internal security control framework that ensures agents can't perform destructive actions — more structured than pattern-matching individual commands.

**Recommendation**: In the SDK architecture, the `can_use_tool` callback provides this systematically. Define a security policy object that the callback evaluates:

```python
SECURITY_POLICY = {
    "blocked_patterns": [r"rm -rf /", r"git push.*--force", r"DROP TABLE"],
    "write_boundary": worktree_path,  # no writes outside worktree
    "blocked_tools": ["mcp__excalidraw__*"],  # irrelevant for code tasks
}

async def enforce_security(tool_name, tool_input):
    return evaluate_policy(SECURITY_POLICY, tool_name, tool_input)
```

---

## 6. Phase-by-Phase Determinism Analysis

Classification of every pipeline step as **D** (deterministic — pure code), **L** (LLM required — needs intelligence), or **H** (hybrid — deterministic setup + LLM for the creative part).

### Summary

| Phase | D Steps | L Steps | H Steps | Token Savings | Can Eliminate LLM? |
|-------|---------|---------|---------|---------------|-------------------|
| 0: Tool Discovery | 8 | 0 | 0 | ~95% | **YES** |
| 1: Source Ingestion | 10 | 1 (inline interview) | 0 | ~80% | YES (Jira/file) |
| 2: Codebase Exploration | 5 | 2 | 0 | ~40-50% | No |
| 3: Branch + OpenSpec | 7 | 2 (spec, tasks) | 1 (proposal) | ~30% | No |
| 4: Plan Review | 3 | 2 (review, fixes) | 0 | ~20% | No |
| 5: Human Checkpoint | 4 | 0 | 0 | ~95% | **YES** |
| 6: Beads Issues | 4 | 0 | 0 | ~98% | **YES** |
| 7: Implementation | 5 | 1 (the big one) | 0 | ~10-15% | No |
| 8: Test Verification | 6 | 2 (failure analysis) | 1 | ~40% | Only if tests pass |
| 9: Review Gate | 4 | 2 (review, fixes) | 0 | ~20% | No |
| 10: Local Dev | 3 | 0 | 1 | ~90% | **YES** |
| 11: PR Creation | 6 | 0 | 1 (PR body) | ~70% | Mostly |

**Overall: ~50-60% token savings.** The LLM currently processes 760 lines of instructions and mediates every bash/git/CLI operation. In the SDK architecture, it receives only focused prompts for the 7-9 calls that require intelligence.

### Phase 0: Tool Discovery — **100% Deterministic**

All 8 steps (tool checks, arg parsing, input routing, session detection, resume prompt) are pure code. The LLM currently does `argparse` and `regex` work that a Python function handles identically every time.

**Non-determinism risk**: The LLM input router runs as pattern matching rather than deterministic regex. A file path that coincidentally matches `[A-Z]+-\d+` could be misrouted. Python `re.match()` eliminates this.

### Phase 1: Source Ingestion — **90% Deterministic**

Jira ingestion (MCP call + field mapping), file ingestion (YAML parse + section extraction), and sufficiency checks are pure code. Only the **inline interview** (adaptive questioning based on input richness) needs LLM.

### Phase 2: Codebase Exploration — **Hybrid (2a/2b split)**

**Phase 2a** (deterministic): Repo structure, package metadata, CI config, test infrastructure, convention files, git history, keyword grep. See Section 5.2 for the full pre-fetch script.

**Phase 2b** (LLM): Receives the pre-fetched bundle. Explores architecture, module boundaries, integration patterns that deterministic search can't cover.

**Non-determinism risk**: HIGH — this is the most variable phase. Each of 8 field runs explored different files. SDLC-3019 failed because CI config was never examined. The 2a/2b split fixes the baseline.

### Phase 3: Branch + OpenSpec — **70% Deterministic**

All scaffolding (branch, worktree, deps, progress file, directory creation, openspec validate) is code. Spec content generation (proposal.md, spec.md with Gherkin, tasks.md) requires LLM.

**Non-determinism risk**: Gherkin scenarios vary in specificity across runs. PR #599 had `spec.links` vs `metadata.links` mismatch — the LLM hallucinated an API detail. Structured output (JSON schema) for spec generation would constrain this.

### Phases 4, 9: Review Gates — **Orchestration is Deterministic**

Git operations, progress updates, verdict branching (PASS/NEEDS_WORK) — all code. The review itself and fix application need LLM. The SDK's `ClaudeSDKClient` can interrupt a review agent that goes off-topic.

### Phase 5: Human Checkpoint — **100% Deterministic**

Template rendering + user input routing. Zero LLM needed.

### Phase 6: Beads Issues — **100% Deterministic**

Parse tasks.md, count entries, run `bd create` CLI commands, capture JSON output. Zero LLM needed.

### Phase 7: Implementation — **Orchestration Deterministic, Core is LLM**

Claim/close lifecycle, progress tracking, parallel dispatch — all code. The implementation sub-agent is the irreducible LLM work (~85-90% of phase cost).

### Phase 8: Test Verification — **Deterministic Unless Tests Fail**

Test command detection (heuristic), lint execution, test execution, retry counting — all code. Only failure analysis and fix application need LLM. With CI autofix (Section 5.13), deterministic fixes run first.

### Phase 10: Local Dev — **100% Deterministic**

Grep for dev command, start process, render checklist, wait for input. Could be eliminated entirely with CI-based smoke tests.

### Phase 11: PR Creation — **90% Deterministic**

Push, `gh pr create`, worktree removal, issue closing — all code. Only PR body summary (diff → human-readable bullets) needs a focused LLM call.

---

## 7. Target Architecture: Python Orchestrator

The minimum viable "code controls LLM" architecture. Every phase transition is a Python function call, not an LLM decision. The LLM never decides "what phase am I in" — the code does.

### Architecture Sketch

```
dark_factory.py (~300 lines)
│
├── phase0_discover(args) -> Config              # argparse, command -v, session detect
├── phase1_ingest(config) -> Ticket              # jira CLI / file read / yaml parse
│     └── [LLM] interview(raw_text) -> Ticket    # only for inline mode
├── phase2_explore(ticket, repo) -> Context
│     ├── phase2a_prefetch(repo) -> Bundle       # deterministic: ls, cat, grep, git log
│     └── [LLM] phase2b_explore(bundle, ticket) -> Findings
├── phase3_scaffold(config, ticket) -> Worktree
│     ├── create_branch_worktree()               # git operations
│     ├── install_deps()                         # lockfile detection
│     ├── write_progress_file()                  # JSON state
│     ├── [LLM] generate_spec(ticket, context) -> OpenSpecFiles
│     └── validate_spec()                        # openspec CLI
├── phase4_review(spec, context) -> ReviewResult
│     ├── [LLM] review_plan(spec, context) -> Verdict
│     └── commit_spec()                          # git add/commit
├── phase5_checkpoint(spec) -> Decision          # template + user input
├── phase6_create_issues(tasks) -> IssueIDs      # bd CLI calls
├── phase7_implement(issues, spec, worktree)
│     └── for issue in issues:
│           ├── claim(issue)                     # bd update --claim
│           ├── [LLM] implement(issue, spec)     # ClaudeSDKClient
│           ├── close(issue)                     # bd close
│           └── update_progress()
├── phase8_verify(worktree) -> TestResult
│     ├── detect_test_cmd(worktree) -> str       # heuristic
│     ├── run_autofix()                          # eslint --fix, black, etc.
│     ├── run_tests(cmd)                         # subprocess
│     └── if fail: [LLM] fix_tests()             # focused prompt
├── phase9_review_impl(spec, diff) -> Verdict
│     ├── get_diff()                             # git diff
│     ├── [LLM] review_code(spec, diff) -> Verdict
│     └── if needs_fix: [LLM] apply_fixes()
├── phase10_local_dev(worktree)                  # detect cmd, start, checklist
└── phase11_create_pr(config, worktree)
      ├── push_branch()                          # git push
      ├── [LLM] generate_pr_body(diff) -> str    # focused summary
      ├── create_pr()                            # gh pr create
      └── cleanup()                              # worktree remove, bd close
```

### LLM Calls (7-9 per run)

| # | Call | SDK Mode | Model | `max_turns` | Tools |
|---|------|----------|-------|-------------|-------|
| 1 | Inline interview | `query()` | sonnet | 5 | None (conversation only) |
| 2 | Codebase exploration | `query()` | sonnet | 15 | Read, Glob, Grep |
| 3 | Spec generation | `query()` | opus | 10 | Read, Glob, Grep |
| 4 | Plan review | `query()` | sonnet | 10 | Read, Glob, Grep |
| 5-N | Implementation (per issue) | `ClaudeSDKClient` | opus | 30 | Read, Edit, Write, Bash, Glob, Grep |
| N+1 | Test failure fix (conditional) | `query()` | opus | 15 | Read, Edit, Bash, Glob, Grep |
| N+2 | Code review | `query()` | sonnet | 10 | Read, Glob, Grep |
| N+3 | Review fix (conditional) | `query()` | opus | 10 | Read, Edit, Bash |
| N+4 | PR body generation | `query()` | sonnet | 3 | None |

### Implementation Details

**State management** — JSON, not markdown:

```python
@dataclass
class PipelineState:
    source: SourceInfo
    config: Config
    current_phase: int
    completed_phases: list[int]
    worktree_path: Path
    branch: str
    epic_id: str | None
    issues: list[IssueState]
    phase_timings: dict[int, float]
    total_cost_usd: float

    def save(self):
        path = self.config.repo_root / ".dark-factory" / f"{self.source.id}.json"
        path.write_text(json.dumps(asdict(self), default=str))

    @classmethod
    def load(cls, path: Path) -> "PipelineState":
        return cls(**json.loads(path.read_text()))
```

**Phase execution with timing and cost tracking**:

```python
async def run_phase(state: PipelineState, phase: int, fn, *args):
    start = time.monotonic()
    try:
        result = await fn(*args)
        state.phase_timings[phase] = time.monotonic() - start
        state.completed_phases.append(phase)
        state.current_phase = phase + 1
        state.save()
        return result
    except Exception as e:
        state.save()  # preserve state for --resume
        raise PipelineError(f"Phase {phase} failed: {e}")
```

**Implementation sub-agent with interrupt guard**:

```python
async def implement_issue(issue: Issue, spec: str, worktree: Path, state: PipelineState):
    async with ClaudeSDKClient(ClaudeCodeOptions(
        model="claude-opus-4-6",
        allowed_tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
        permission_mode="acceptEdits",
        max_turns=30,
        cwd=str(worktree),
        system_prompt=build_impl_prompt(issue, spec),
        can_use_tool=lambda name, input: enforce_security(SECURITY_POLICY, name, input),
    )) as client:
        await client.connect()
        await client.query(f"Implement: {issue.title}\n\n{issue.description}")
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                state.total_cost_usd += msg.total_cost_usd
                if not msg.is_success:
                    raise ImplementationError(issue.id, msg.result)
```

**Deterministic pre-fetch** (Phase 2a):

```python
def prefetch_context(repo: Path) -> ContextBundle:
    bundle = ContextBundle()
    bundle.structure = subprocess.run(["ls", "-1", str(repo)], capture_output=True, text=True).stdout
    for f in ["package.json", "pyproject.toml", "go.mod"]:
        p = repo / f
        if p.exists():
            bundle.project_metadata[f] = p.read_text()
    for pattern in ["blackbird.yaml", "buildspec.yml", ".github/workflows/*.yml", "Dockerfile"]:
        for match in repo.glob(pattern):
            bundle.ci_config[match.name] = match.read_text()
    for f in ["CLAUDE.md", "AGENTS.md", ".cursorrules"]:
        p = repo / f
        if p.exists():
            bundle.conventions[f] = p.read_text()
    bundle.recent_commits = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", "-20"],
        capture_output=True, text=True
    ).stdout
    # Test infrastructure detection
    for pattern in ["jest.config*", "pytest.ini", "conftest.py", "vitest.config*"]:
        bundle.test_config.extend(str(p) for p in repo.rglob(pattern))
    return bundle
```

---

## 8. Recommended Evolution Path

Restructured around the "code controls LLM" migration. The old Phase A-E incremental path is replaced by a migration sequence that builds the Python orchestrator incrementally.

### Step 1: Extract Fully Deterministic Phases (1-2 days)

Create `dark_factory.py` with Phases 0, 5, 6, 10 as Python functions. The existing markdown command delegates to `python3 dark_factory.py phase0 "$ARGUMENTS"` and reads structured output. This is a **partial extraction** that coexists with the current command.

| What moves to Python | Current LLM cost | Post-migration |
|---------------------|-------------------|----------------|
| Phase 0: arg parsing, tool discovery, session detect | ~95% waste | Zero tokens |
| Phase 5: template rendering, user input routing | ~95% waste | Zero tokens |
| Phase 6: `bd create` CLI calls from parsed tasks | ~98% waste | Zero tokens |
| Phase 10: dev server start, checklist rendering | ~90% waste | Zero tokens |

Also add: JSON progress file (replaces markdown), phase timing, cost tracking via `ResultMessage` fields.

### Step 2: Extract Ingestion + Deterministic Pre-Fetch (2-3 days)

Move Phase 1 (Jira/file ingestion) and Phase 2a (deterministic pre-fetch) to Python. Only inline interview and Phase 2b exploration remain as LLM calls.

| What moves to Python | Impact |
|---------------------|--------|
| Jira field extraction + mapping | 100% deterministic |
| File read + YAML parse + section extraction | 100% deterministic |
| Phase 2a: repo scan, CI config, test infra, conventions | Fixes SDLC-3019, saves 30-50% Phase 2 tokens |
| Sufficiency check, slug collision | 100% deterministic |

### Step 3: Orchestration Loop (1 week)

Move the Phase 7 claim/close/progress loop, Phase 8 test detection/execution/retry counting, and Phase 11 push/PR/cleanup into Python. LLM calls become `claude-code-sdk` invocations with focused prompts, `max_turns`, and `allowed_tools`.

Key SDK features to wire up:
- `ClaudeSDKClient` with `interrupt()` for Phase 7 implementation agents
- `can_use_tool` callback for security policy enforcement
- `allowed_tools` per sub-agent type (see Section 5.3)
- CI autofix before LLM escalation in Phase 8 (Section 5.13)
- `ResultMessage` cost/timing for per-phase observability

### Step 4: Full Python Orchestrator (1-2 weeks)

The markdown command becomes a thin launcher: `python3 dark_factory.py "$ARGUMENTS"`. The Python script owns the entire state machine. The LLM is called only for the 7-9 steps in the [architecture sketch](#7-target-architecture-python-orchestrator).

Add quality gates:
- Diff-size guard before PR creation
- SAST step (`semgrep --config auto --diff`)
- Dependency audit (`npm audit` / `pip-audit`)
- Scoped rule file injection (scan for `.cursorrules`/CLAUDE.md per directory)

### Step 5: Advanced Features (ongoing)

| Feature | Effort | When |
|---------|--------|------|
| In-process MCP tools (`save_progress`, `check_ci`) | Moderate | After Step 4 |
| Holdout test scenarios (spec/holdout split) | Architecture | When quality gates are stable |
| GitHub Action for PR review feedback loop | New workflow | When pipeline is reliable |
| Probabilistic test gates (StrongDM 2/3 pattern) | Moderate | When running 10+ pipelines/day |
| Auto-memory save (test durations, repo patterns) | ~10 lines | After Step 3 |
| Jira status transition on PR creation | ~5 lines | After Step 3 |

---

## 9. Sources

### Autonomous AI Coding Research
- [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Martin Fowler / ThoughtWorks: How Far Can We Push AI Autonomy in Code Generation?](https://martinfowler.com/articles/pushing-ai-autonomy.html)
- [Spotify Engineering: Background Coding Agents — Feedback Loops (Part 3)](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- [Anthropic: Measuring AI Agent Autonomy in Practice](https://www.anthropic.com/research/measuring-agent-autonomy)
- [Anthropic: 2026 Agentic Coding Trends Report](https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf)

### Stripe Minions (Comparative Reference)
- [Stripe Engineering: Minions Part 1 — One-Shot, End-to-End Coding Agents](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Stripe Engineering: Minions Part 2 — Architecture Deep Dive](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)

### Orchestration & Architecture
- [Microsoft Azure: AI Agent Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- [SkyWork: 20 Agentic AI Workflow Patterns](https://skywork.ai/blog/agentic-ai-examples-workflow-patterns-2025/)
- [Stack AI: 2026 Guide to Agentic Workflow Architectures](https://www.stack-ai.com/blog/the-2026-guide-to-agentic-workflow-architectures)

### Security & Risk
- [USENIX: Package Hallucinations — Comprehensive Analysis](https://www.usenix.org/publications/loginonline/we-have-package-you-comprehensive-analysis-package-hallucinations-code)
- [Dark Reading: As Coders Adopt AI Agents, Security Pitfalls Lurk in 2026](https://www.darkreading.com/application-security/coders-adopt-ai-agents-security-pitfalls-lurk-2026)
- [arXiv: Security Degradation in Iterative AI Code Generation](https://arxiv.org/pdf/2506.11022)
- [SkyWork: Agentic AI Safety & Guardrails — 2025 Best Practices](https://skywork.ai/blog/agentic-ai-safety-best-practices-2025-enterprise/)

### Industry Landscape
- [Pullflow: 1 in 7 PRs Now Involve AI Agents (2025)](https://pullflow.com/state-of-ai-code-review-2025)
- [Diffblue: Towards Autonomous AI Coding Agents](https://www.diffblue.com/resources/towards-autonomous-ai-coding-agents-the-future-of-software-development/)
- [OpenAI Cookbook: Automate Jira to GitHub with Codex](https://cookbook.openai.com/examples/codex/jira-github)
- [Atlassian: AI-Powered Workflows with Rovo Dev](https://www.atlassian.com/blog/bitbucket/ai-powered-workflows-rovodev)

### Claude Code Documentation
- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide.md)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions.md)
- [Claude Code Headless Mode](https://code.claude.com/docs/en/headless.md)
- [Claude Code GitHub Action](https://code.claude.com/docs/en/github-actions.md)
- [Claude Code SDK (Python)](https://pypi.org/project/claude-code-sdk/) — `claude-code-sdk` v0.0.25+
- [Claude Code SDK (npm)](https://www.npmjs.com/package/@anthropic-ai/claude-code) — `@anthropic-ai/claude-code` v2.1.76+
- [Claude API Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md)

### Cost & Operations
- [Medium: Cost Guardrails for Agent Fleets](https://medium.com/@Micheal-Lanham/cost-guardrails-for-agent-fleets-how-to-prevent-your-ai-agents-from-burning-through-your-budget-ea68722af3fe)
- [Gartner: 40% of Agentic AI Projects Will Be Canceled by 2027](https://www.gartner.com/en/newsroom/press-releases/2025-03-agentic-ai-projects)
