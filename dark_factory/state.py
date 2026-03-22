"""Pipeline state management with JSON serialization.

State is owned entirely by the orchestrator -- the LLM never reads or
writes these files.  Stored at .dark-factory/<KEY>.json relative to the
repo root.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SourceInfo:
    """Describes how the pipeline was invoked."""

    kind: str  # "jira", "file", or "inline"
    raw: str  # original argument string
    id: str  # normalized key used for state file naming (e.g. "sdlc-123")


@dataclass
class PipelineState:
    """Full pipeline state, serialized to JSON between phases."""

    source: SourceInfo
    repo_root: str  # absolute path to the repo root
    current_phase: float = 0
    completed_phases: list[float] = field(default_factory=list)
    worktree_path: str = ""
    branch: str = ""
    epic_id: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    phase_timings: dict[str, float] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    dry_run: bool = False
    error: str | None = None
    visible_test_paths: list[str] = field(default_factory=list)
    holdout_test_paths: list[str] = field(default_factory=list)
    max_parallel: int = 3

    # -- persistence -------------------------------------------------------

    def _state_dir(self) -> Path:
        return Path(self.repo_root) / ".dark-factory"

    def _state_path(self) -> Path:
        return self._state_dir() / f"{self.source.id}.json"

    def save(self) -> Path:
        """Write state to .dark-factory/<KEY>.json.  Returns the path written."""
        state_dir = self._state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_path()
        path.write_text(json.dumps(asdict(self), indent=2, default=str))
        return path

    @classmethod
    def load(cls, path: Path) -> PipelineState:
        """Reconstruct state from a JSON file."""
        raw = json.loads(path.read_text())
        raw["source"] = SourceInfo(**raw["source"])
        return cls(**raw)

    # -- query helpers -----------------------------------------------------

    def is_phase_completed(self, phase: float) -> bool:
        return phase in self.completed_phases

    def next_phase(self) -> float:
        """Return the first uncompleted phase (for --resume)."""
        return self.current_phase


class PipelineError(Exception):
    """Raised when a phase fails."""

    def __init__(self, phase: float, message: str) -> None:
        self.phase = phase
        super().__init__(f"Phase {phase} failed: {message}")
