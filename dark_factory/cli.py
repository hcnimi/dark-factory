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
    """
    flags = {a for a in argv if a.startswith("--")}
    positional = [a for a in argv if not a.startswith("--")]

    raw_source = " ".join(positional) if positional else ""
    source = _classify_source(raw_source)

    return ParsedArgs(
        source=source,
        dry_run="--dry-run" in flags,
        resume="--resume" in flags,
        missing_tools=_check_tools(),
    )
