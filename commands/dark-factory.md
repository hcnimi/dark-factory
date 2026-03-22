Autonomous spec-to-PR pipeline: $ARGUMENTS

Delegates all orchestration to the `dark_factory` Python package.

## Quick Start

```bash
python3 -m dark_factory run $ARGUMENTS
```

Read the JSON output. If `status` is `"error"`, stop and report.

## Phase Dispatch

All phases are implemented in Python. The orchestrator handles:

- **Phase 0**: Parse args, check tools, init state
- **Phase 1**: Source ingestion (Jira/file/inline)
- **Phase 2**: Codebase exploration (deterministic pre-fetch + SDK)
- **Phase 3**: Branch, worktree, deps, openspec scaffold (SDK)
- **Phase 4**: Plan review gate (SDK)
- **Phase 5**: Human checkpoint (deterministic)
- **Phase 6**: Beads issue creation (deterministic)
- **Phase 7**: Implementation loop (SDK, opus)
- **Phase 8**: Test verification + dependency audit (SDK)
- **Phase 9**: Implementation review + diff-size guard (SDK)
- **Phase 10**: Local dev verification (deterministic)
- **Phase 11**: PR creation + cleanup (SDK)

## Individual Phase Access

For targeted re-runs or debugging:

```bash
# Deterministic phases (zero LLM tokens)
python3 -m dark_factory 0 $ARGUMENTS
echo '<json>' | python3 -m dark_factory 5
echo '<json>' | python3 -m dark_factory 6
echo '<json>' | python3 -m dark_factory 10
```

## Rules

- If any phase fails, stop and report
- Never skip the human checkpoint (Phase 5)
- One sub-agent per beads issue in Phase 7
- Max 2 test-fix retries in Phase 8
- Max 1 review-fix cycle in Phase 9
- Diff-size guard warns if changes exceed 3x expected
- Dependency audit runs for detected project type
- Completion summary prints per-phase timing, cost, and turns

## Usage

```
/dark-factory <jira-key|file|description> [--dry-run] [--resume]
```
