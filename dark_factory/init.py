"""``dark-factory init`` — scaffold Claude Code integration into a target repo.

Writes the /dark-factory slash command into .claude/commands/ so Claude Code
auto-discovers it.  Safe to re-run: overwrites existing command file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The slash command template that gets written into the target repo.
# This is the same content that was previously in commands/dark-factory.md.
_COMMAND_TEMPLATE = """\
Autonomous spec-to-PR pipeline: $ARGUMENTS

Delegates all orchestration to the `dark_factory` Python package.

## Quick Start

```bash
dark-factory run $ARGUMENTS
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
dark-factory 0 $ARGUMENTS
echo '<json>' | dark-factory 5
echo '<json>' | dark-factory 6
echo '<json>' | dark-factory 10
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
"""


def run_init(repo_root: str = ".") -> None:
    """Write the /dark-factory slash command into the target repo."""
    root = Path(repo_root).resolve()

    # Verify we're in a git repo
    if not (root / ".git").exists():
        print(f"Error: {root} is not a git repository.", file=sys.stderr)
        sys.exit(1)

    commands_dir = root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    command_path = commands_dir / "dark-factory.md"
    command_path.write_text(_COMMAND_TEMPLATE, encoding="utf-8")

    # Ensure .dark-factory/ is gitignored (runtime state directory)
    gitignore = root / ".gitignore"
    _ensure_gitignore_entry(gitignore, ".dark-factory/")

    print(f"Initialized dark-factory in {root}")
    print(f"  Wrote {command_path.relative_to(root)}")
    print(f"  /dark-factory command is now available in Claude Code")


def _ensure_gitignore_entry(gitignore: Path, entry: str) -> None:
    """Add an entry to .gitignore if it's not already present."""
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content.splitlines():
            return
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = ""

    content += entry + "\n"
    gitignore.write_text(content, encoding="utf-8")
