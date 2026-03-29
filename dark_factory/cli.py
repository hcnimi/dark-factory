"""CLI argument parsing and input routing (Phase 0).

Parses the /dark-factory argument into a SourceInfo, detects flags,
and checks tool availability.  Zero LLM tokens consumed.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .state import SourceInfo


@dataclass
class ParsedArgs:
    """Result of parsing /dark-factory arguments."""

    source: SourceInfo
    dry_run: bool = False
    resume: bool = False
    from_spec: str = ""
    max_cost: float | None = None
    missing_tools: list[str] = field(default_factory=list)


# Jira key: PROJECT-123
_JIRA_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")

# Required external tools
_REQUIRED_TOOLS = ["git", "gh"]


def _classify_source(raw: str) -> SourceInfo:
    """Determine input type from the raw argument string."""
    stripped = raw.strip().strip('"').strip("'")

    if _JIRA_RE.match(stripped):
        return SourceInfo(kind="jira", raw=stripped, id=stripped.lower())

    # File path heuristic: contains / or . with an extension
    if "/" in stripped or (
        "." in stripped and Path(stripped).suffix in (".md", ".yaml", ".yml", ".txt")
    ):
        return SourceInfo(kind="file", raw=stripped, id=Path(stripped).stem.lower())

    return SourceInfo(kind="inline", raw=stripped, id=_slugify(stripped))


def _slugify(text: str) -> str:
    """Create a filesystem-safe identifier from free text."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] if slug else "inline"


def _check_tools() -> list[str]:
    """Return names of required tools that are not on PATH."""
    return [t for t in _REQUIRED_TOOLS if shutil.which(t) is None]


def parse_args(argv: list[str]) -> ParsedArgs:
    """Parse the raw argument list from /dark-factory invocation.

    Expected forms:
        ["SDLC-123"]
        ["SDLC-123", "--resume"]
        ["specs/feature.md", "--dry-run"]
        ["add dark mode toggle"]
        ["--from-spec", "openspec/changes/dark-factory-sdlc-123"]
    """
    # Extract --from-spec and --max-cost values before general flag/positional parsing
    from_spec = ""
    max_cost: float | None = None
    filtered: list[str] = []
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg == "--from-spec" and i + 1 < len(argv):
            from_spec = argv[i + 1]
            skip_next = True
        elif arg.startswith("--from-spec="):
            from_spec = arg.split("=", 1)[1]
        elif arg == "--max-cost" and i + 1 < len(argv):
            max_cost = float(argv[i + 1])
            skip_next = True
        elif arg.startswith("--max-cost="):
            max_cost = float(arg.split("=", 1)[1])
        else:
            filtered.append(arg)

    flags = {a for a in filtered if a.startswith("--")}
    positional = [a for a in filtered if not a.startswith("--")]

    if from_spec and not positional:
        # Derive source from the spec directory name
        change_id = Path(from_spec).name
        source = SourceInfo(kind="spec", raw=from_spec, id=change_id)
    else:
        raw_source = " ".join(positional) if positional else ""
        source = _classify_source(raw_source)

    return ParsedArgs(
        source=source,
        dry_run="--dry-run" in flags,
        resume="--resume" in flags,
        from_spec=from_spec,
        max_cost=max_cost,
        missing_tools=_check_tools(),
    )
