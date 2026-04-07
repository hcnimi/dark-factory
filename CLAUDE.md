# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# dark-factory

Three-component autonomous spec-to-PR orchestration (v2.0.0). Takes a Jira ticket, spec file, directory of specs, or inline description and produces a ready-to-review pull request via Claude Code SDK agents.

## Development

```bash
pip install -e .                          # Editable install
python3 -m pytest tests/                  # Run all tests
python3 -m pytest tests/test_intent.py    # Single test file
python3 -m pytest tests/test_intent.py::test_function_name  # Single test
python3 -m pytest tests/ -x              # Stop on first failure
```

**Run the pipeline:**
```bash
dark-factory run <jira-key|file|dir|description> [--dry-run] [--gate-intent] [--gate-eval] [--in-place] [--analyze-spec] [--no-assess]
dark-factory run --resume <run-id>        # Resume from gate
```

**Phased CLI commands** (used by the slash command orchestrator):
```bash
dark-factory prepare <run-id>             # Create worktree + prompt files
dark-factory verify <run-id>              # Run tests + capture diff
dark-factory evaluate --run <run-id>      # Score implementation
dark-factory evaluate <branch>            # Standalone branch evaluation
dark-factory complete <run-id>            # Finalize after eval gate
```

**Initialize in a target repo:**
```bash
dark-factory init    # Writes .claude/commands/dark-factory.md + .dark-factory/
```

## Architecture

The pipeline has three core components that run sequentially:

1. **Intent Clarification** (`intent.py`, `interview.py`) — Produces a structured `IntentDocument` (title, summary, acceptance criteria) from raw input. Two modes: *extraction* preserves detail from structured specs (detecting Gherkin/requirement markers); *condensation* synthesizes structure from vague input. Optional `interview.py` assessment asks clarifying questions first.

2. **Implementation** (`infra.py`) — Creates a git worktree, launches an Opus SDK agent with a security-gated `can_use_tool` callback, runs tests, and captures the diff. One fix retry on test failure (budget permitting).

3. **Evaluation** (`evaluator.py`) — Adversarial scoring by a fresh Sonnet agent that never sees the implementation conversation. Scores on Intent Fidelity, Correctness, and Integration (0-10 each) plus per-criterion met/partial/not_met.

### Key modules

- `types.py` — All dataclasses and enums (`RunState`, `IntentDocument`, `EvaluationReport`, `SourceInfo`, `RunConfig`, etc.). Also contains `extract_sdk_result()` for parsing SDK responses.
- `__main__.py` — CLI entry point, argument parsing, pipeline orchestration for both fresh runs and gate-resume flows.
- `state.py` — JSONL event logging (`log_event`).
- `security.py` — `SecurityPolicy` enforcement: blocked bash patterns, write boundary, blocked tools. Used as `can_use_tool` callback for SDK agents.
- `infra.py` — Worktree lifecycle, test detection/running, agent launch (`_launch_agent`), `IMPLEMENTATION_SYSTEM_PROMPT`.
- `spec_analyzer.py` — Optional post-intent quality check (Clarity/Testability/Completeness scoring).
- `commands/dark-factory.md` — The Claude Code slash command template installed by `dark-factory init`.

### State & Resumability

Pipeline state persists to `.dark-factory/<run_id>.json` as a serialized `RunState`. Side-files: `.diff`, `.evaluation.json`, `.events.jsonl`, `.prompt.md`, `.system.md`, `.source.md`. Exit code 75 (`EXIT_GATED`) signals a gate pause for the orchestrator to resume.

### Gate system

Two optional gates: `--gate-intent` (after intent clarification) and `--gate-eval` (after evaluation). In TTY mode, gates prompt via `input()`. In non-TTY mode (slash command), they emit JSON with `__gate__` marker and exit 75. The slash command orchestrator (in `commands/dark-factory.md`) always injects `--gate-intent`.

### SDK agent pattern

All LLM calls follow the same pattern: build a system prompt + user prompt, call `claude_code_sdk.query()` with `ClaudeCodeOptions`, collect messages, extract text+cost via `extract_sdk_result()`. Non-tool agents (intent, evaluation, interview, spec analysis) use `allowed_tools=[]` and `max_turns=3`. The implementation agent uses Opus with full tool access and `max_turns=30`.

## Dependencies

- **Python 3.11+**, **hatchling** build system
- **Runtime:** `claude-code-sdk>=0.0.25`, `git`, `gh`
- No other Python dependencies

## Principles

- Composition over inheritance
- Security first — blocked patterns, write boundaries on every agent invocation
- Comments explain WHY not WHAT
- All data types live in `types.py`; modules import from there, not from each other's internals
