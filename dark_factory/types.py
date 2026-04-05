"""All data types for dark-factory v2."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceKind(str, Enum):
    JIRA = "jira"
    FILE = "file"
    INLINE = "inline"


class RunStatus(str, Enum):
    PENDING = "pending"
    INTENT_COMPLETE = "intent_complete"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"


class Gate(str, Enum):
    INTENT = "intent"
    EVAL = "eval"


class CriterionStatus(str, Enum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------

_JIRA_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


@dataclass(frozen=True)
class SourceInfo:
    kind: SourceKind
    raw: str
    id: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "raw": self.raw, "id": self.id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SourceInfo:
        return cls(kind=SourceKind(d["kind"]), raw=d["raw"], id=d["id"])


def classify_source(raw: str) -> SourceInfo:
    """Classify raw CLI input into a SourceInfo."""
    stripped = raw.strip()
    if _JIRA_RE.match(stripped):
        return SourceInfo(kind=SourceKind.JIRA, raw=stripped, id=stripped)
    if Path(stripped).is_file():
        return SourceInfo(kind=SourceKind.FILE, raw=stripped, id=Path(stripped).stem)
    # Everything else is inline
    slug = re.sub(r"[^a-z0-9]+", "-", stripped.lower())[:40].strip("-")
    return SourceInfo(kind=SourceKind.INLINE, raw=stripped, id=slug or "inline")


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------

@dataclass
class IntentDocument:
    title: str
    summary: str
    acceptance_criteria: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "acceptance_criteria": self.acceptance_criteria,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntentDocument:
        return cls(
            title=d["title"],
            summary=d["summary"],
            acceptance_criteria=d["acceptance_criteria"],
        )

    def format_for_display(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            self.summary,
            "",
            "## Acceptance Criteria",
        ]
        for i, ac in enumerate(self.acceptance_criteria, 1):
            lines.append(f"  {i}. {ac}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    dimension: str
    score: int
    justification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "justification": self.justification,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DimensionScore:
        return cls(
            dimension=d["dimension"],
            score=d["score"],
            justification=d["justification"],
        )


@dataclass
class CriterionAssessment:
    criterion: str
    status: CriterionStatus
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "status": self.status.value,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CriterionAssessment:
        return cls(
            criterion=d["criterion"],
            status=CriterionStatus(d["status"]),
            evidence=d["evidence"],
        )


@dataclass
class EvaluationReport:
    scores: list[DimensionScore]
    criteria: list[CriterionAssessment]
    model_used: str
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": [s.to_dict() for s in self.scores],
            "criteria": [c.to_dict() for c in self.criteria],
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvaluationReport:
        return cls(
            scores=[DimensionScore.from_dict(s) for s in d["scores"]],
            criteria=[CriterionAssessment.from_dict(c) for c in d["criteria"]],
            model_used=d["model_used"],
            cost_usd=d["cost_usd"],
        )

    def is_borderline(self) -> bool:
        """Any dimension scoring 5-7 is borderline."""
        return any(5 <= s.score <= 7 for s in self.scores)

    def is_passing(self) -> bool:
        """All dimensions 8+ is passing."""
        return all(s.score >= 8 for s in self.scores)

    def format_for_display(self) -> str:
        lines = ["## Evaluation Report", ""]
        lines.append("### Scores")
        for s in self.scores:
            lines.append(f"  - **{s.dimension}**: {s.score}/10 — {s.justification}")
        lines.append("")
        lines.append("### Acceptance Criteria")
        for c in self.criteria:
            icon = {"met": "+", "partial": "~", "not_met": "-"}[c.status.value]
            lines.append(f"  [{icon}] {c.criterion}: {c.evidence}")
        lines.append("")
        lines.append(f"Model: {self.model_used} | Cost: ${self.cost_usd:.4f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@dataclass
class SecurityPolicy:
    blocked_patterns: list[str] = field(default_factory=list)
    write_boundary: Path | None = None
    blocked_tools: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    max_cost_usd: float = 10.0
    evaluator_model: str = "claude-sonnet-4-20250514"
    gates: list[Gate] = field(default_factory=list)
    in_place: bool = False
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "evaluator_model": self.evaluator_model,
            "gates": [g.value for g in self.gates],
            "in_place": self.in_place,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunConfig:
        return cls(
            max_cost_usd=d.get("max_cost_usd", 10.0),
            evaluator_model=d.get("evaluator_model", "claude-sonnet-4-20250514"),
            gates=[Gate(g) for g in d.get("gates", [])],
            in_place=d.get("in_place", False),
            dry_run=d.get("dry_run", False),
        )


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class RunState:
    run_id: str
    source: SourceInfo
    config: RunConfig
    status: RunStatus = RunStatus.PENDING
    intent: IntentDocument | None = None
    worktree_path: str = ""
    branch: str = ""
    base_branch: str = "main"
    cost_usd: float = 0.0
    diff: str = ""
    evaluation: EvaluationReport | None = None
    test_command: str = ""
    error: str = ""

    @classmethod
    def create(cls, source: SourceInfo, config: RunConfig) -> RunState:
        return cls(run_id=_new_run_id(), source=source, config=config)

    def state_dir(self, repo_root: str) -> Path:
        d = Path(repo_root) / ".dark-factory"
        d.mkdir(exist_ok=True)
        return d

    def state_path(self, repo_root: str) -> Path:
        return self.state_dir(repo_root) / f"{self.run_id}.json"

    def events_path(self, repo_root: str) -> Path:
        return self.state_dir(repo_root) / f"{self.run_id}.events.jsonl"

    def evaluation_path(self, repo_root: str) -> Path:
        return self.state_dir(repo_root) / f"{self.run_id}.evaluation.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source": self.source.to_dict(),
            "config": self.config.to_dict(),
            "status": self.status.value,
            "intent": self.intent.to_dict() if self.intent else None,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "cost_usd": self.cost_usd,
            "test_command": self.test_command,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        return cls(
            run_id=d["run_id"],
            source=SourceInfo.from_dict(d["source"]),
            config=RunConfig.from_dict(d["config"]),
            status=RunStatus(d["status"]),
            intent=IntentDocument.from_dict(d["intent"]) if d.get("intent") else None,
            worktree_path=d.get("worktree_path", ""),
            branch=d.get("branch", ""),
            base_branch=d.get("base_branch", "main"),
            cost_usd=d.get("cost_usd", 0.0),
            test_command=d.get("test_command", ""),
            error=d.get("error", ""),
        )

    def save(self, repo_root: str) -> Path:
        path = self.state_path(repo_root)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: Path) -> RunState:
        return cls.from_dict(json.loads(path.read_text()))


class DarkFactoryError(Exception):
    """Base error for dark-factory operations."""


def extract_sdk_result(messages: list) -> tuple[str, float]:
    """Extract text and cost from SDK query messages.

    The SDK yields UserMessage, AssistantMessage, SystemMessage, ResultMessage,
    and StreamEvent. Cost lives on ResultMessage.total_cost_usd, final text on
    ResultMessage.result. Falls back to AssistantMessage content blocks.
    """
    text = ""
    cost = 0.0

    for msg in messages:
        # ResultMessage has the authoritative result and cost
        if hasattr(msg, "total_cost_usd"):
            cost = msg.total_cost_usd or 0.0
            if hasattr(msg, "result") and msg.result:
                text = msg.result

    # Fallback: if no ResultMessage.result, extract from AssistantMessage blocks
    if not text:
        parts = []
        for msg in messages:
            if hasattr(msg, "content") and isinstance(msg.content, list):
                for block in msg.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
        text = "\n".join(parts)

    return text, cost
