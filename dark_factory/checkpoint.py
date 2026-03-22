"""Phase 5: human checkpoint — render plan summary, return decision.

Presents the reviewed plan as formatted text and captures the human's
choice (approve / modify / abort).  Zero LLM tokens consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Decision(Enum):
    APPROVE = "approve"
    MODIFY = "modify"
    ABORT = "abort"


@dataclass
class PlanSummary:
    """All the pieces needed to render the Phase 5 checkpoint prompt."""

    external_ref: str
    summary: str
    branch: str
    worktree_path: str
    review_result: str  # "PASS" or "issues addressed: ..."
    spec_overview: str  # 1-2 sentence overview
    requirements: list[str]  # requirement names from spec.md
    tasks: list[str]  # task lines from tasks.md (preserving [P] markers)


def render_checkpoint(plan: PlanSummary, dry_run: bool = False) -> str:
    """Build the formatted checkpoint prompt shown to the human."""
    req_lines = "\n".join(f"  - {r}" for r in plan.requirements)
    task_lines = "\n".join(
        f"  {i}. {t}" for i, t in enumerate(plan.tasks, 1)
    )

    text = f"""\
{'=' * 45}
DARK FACTORY — Plan Review
{'=' * 45}

Source: {plan.external_ref} — {plan.summary}
Branch: {plan.branch}
Worktree: {plan.worktree_path}
Plan review: {plan.review_result}

## Spec Summary
{plan.spec_overview}

## Requirements ({len(plan.requirements)})
{req_lines}

## Implementation Plan ({len(plan.tasks)} tasks)
{task_lines}

{'=' * 45}"""

    if dry_run:
        text += "\n\nDry run complete. No implementation performed."
    else:
        text += """

(A) Approve — proceed to implementation
(B) Adjust — provide feedback (will re-review)
(C) Abort — clean up and stop"""

    return text


def parse_decision(response: str) -> Decision:
    """Map a human response string to a Decision enum.

    Accepts the letter (A/B/C) or the word (approve/adjust/abort),
    case-insensitive.
    """
    cleaned = response.strip().lower()

    if cleaned in ("a", "approve"):
        return Decision.APPROVE
    if cleaned in ("b", "adjust", "modify"):
        return Decision.MODIFY
    if cleaned in ("c", "abort"):
        return Decision.ABORT

    raise ValueError(
        f"Unrecognized response: {response!r}. "
        "Expected A/B/C or approve/adjust/abort."
    )


def parse_spec_requirements(spec_text: str) -> list[str]:
    """Extract requirement names from a spec.md file.

    Looks for markdown headings (## or ###) that represent requirements.
    """
    requirements: list[str] = []
    for line in spec_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            requirements.append(stripped[4:].strip())
        elif stripped.startswith("## ") and stripped[3:].strip() not in (
            "Requirements",
            "Scenarios",
            "Acceptance Criteria",
        ):
            requirements.append(stripped[3:].strip())
    return requirements


def parse_tasks(tasks_text: str) -> list[str]:
    """Extract task lines from a tasks.md file.

    Recognises numbered lists (1. task), bullet lists (- task),
    and checkbox lists (- [ ] task / - [x] task).
    """
    tasks: list[str] = []
    for line in tasks_text.splitlines():
        stripped = line.strip()
        # Numbered: "1. Do something" or "1. [P] Do something"
        if stripped and stripped[0].isdigit() and ". " in stripped:
            task = stripped.split(". ", 1)[1]
            tasks.append(task)
        # Bullet / checkbox: "- [ ] task" or "- task"
        elif stripped.startswith("- "):
            task = stripped[2:]
            # Strip checkbox prefix if present
            if task.startswith("[ ] ") or task.startswith("[x] "):
                task = task[4:]
            tasks.append(task)
    return tasks
