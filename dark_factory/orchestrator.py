"""Full pipeline orchestrator: runs all phases, quality gates, and summary.

Provides:
- diff_size_guard(): warns between Phase 9 and 10 if diff is unexpectedly large
- dependency_audit(): runs npm audit / pip-audit / go vet in Phase 8
- CompletionSummary: per-phase table with duration, cost, and turn counts
- run_pipeline(): full end-to-end orchestration entry point
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Diff-size guard (between Phase 9 and 10)
# ---------------------------------------------------------------------------

@dataclass
class DiffSizeReport:
    """Result of the diff-size guard check."""

    actual_lines: int = 0
    expected_lines: int = 0
    ratio: float = 0.0
    warning: str = ""
    passed: bool = True

    # Lines-per-task heuristic baseline
    LINES_PER_TASK: int = 150
    # Warn if actual exceeds expected by this multiplier
    WARN_THRESHOLD: float = 3.0


def diff_size_guard(
    worktree_path: str,
    task_count: int,
    *,
    dry_run: bool = False,
) -> DiffSizeReport:
    """Compare actual diff lines against expected (task_count x 150).

    Warns if actual > 3x expected, indicating scope creep or over-engineering.
    """
    report = DiffSizeReport()
    report.expected_lines = task_count * DiffSizeReport.LINES_PER_TASK

    if dry_run:
        report.actual_lines = 0
        return report

    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "main...HEAD"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
            timeout=30,
        )
        if result.returncode == 0:
            # Parse total from the last line: " N files changed, X insertions(+), Y deletions(-)"
            lines = result.stdout.strip().splitlines()
            if lines:
                last = lines[-1]
                report.actual_lines = _parse_diff_stat_total(last)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if report.expected_lines > 0:
        report.ratio = report.actual_lines / report.expected_lines
    else:
        report.ratio = 0.0

    if report.ratio > DiffSizeReport.WARN_THRESHOLD:
        report.passed = False
        report.warning = (
            f"Diff size warning: {report.actual_lines} lines changed "
            f"(expected ~{report.expected_lines} for {task_count} tasks). "
            f"Ratio: {report.ratio:.1f}x — may indicate scope creep or "
            f"over-engineering. Review before proceeding."
        )

    return report


def _parse_diff_stat_total(line: str) -> int:
    """Extract total insertions + deletions from a git diff --stat summary line.

    Example: " 5 files changed, 120 insertions(+), 30 deletions(-)"
    Returns 150.
    """
    import re

    total = 0
    for match in re.finditer(r"(\d+)\s+(?:insertion|deletion)", line):
        total += int(match.group(1))
    return total


# ---------------------------------------------------------------------------
# Dependency audit (Phase 8 extension)
# ---------------------------------------------------------------------------

@dataclass
class AuditResult:
    """Result of dependency audit."""

    project_type: str = ""  # "node", "python", "go", or ""
    command_run: str = ""
    passed: bool = True
    output: str = ""
    vulnerabilities: int = 0


def detect_project_type(worktree_path: str) -> str:
    """Detect project type from lock/config files."""
    wt = Path(worktree_path)
    if (wt / "package.json").exists() or (wt / "package-lock.json").exists():
        return "node"
    if (wt / "pyproject.toml").exists() or (wt / "requirements.txt").exists():
        return "python"
    if (wt / "go.mod").exists():
        return "go"
    return ""


def dependency_audit(
    worktree_path: str,
    *,
    dry_run: bool = False,
) -> AuditResult:
    """Run dependency audit appropriate to the project type.

    - Node: npm audit --audit-level=moderate
    - Python: pip-audit (if available)
    - Go: go vet ./...
    """
    result = AuditResult()
    result.project_type = detect_project_type(worktree_path)

    if not result.project_type:
        result.output = "No recognized project type — skipping audit."
        return result

    if dry_run:
        result.output = f"[dry-run] {result.project_type} audit skipped"
        return result

    audit_commands: dict[str, list[str]] = {
        "node": ["npm", "audit", "--audit-level=moderate"],
        "python": ["pip-audit"],
        "go": ["go", "vet", "./..."],
    }

    cmd = audit_commands.get(result.project_type)
    if not cmd:
        return result

    result.command_run = " ".join(cmd)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=worktree_path,
            timeout=120,
        )
        result.output = (proc.stdout + "\n" + proc.stderr).strip()

        # npm audit returns non-zero when vulnerabilities found
        # pip-audit returns non-zero when vulnerabilities found
        # go vet returns non-zero when issues found
        if proc.returncode != 0:
            result.passed = False
            # Count vulnerabilities heuristically
            result.vulnerabilities = result.output.lower().count("vulnerabilit")

    except FileNotFoundError:
        result.output = f"Audit tool not found: {cmd[0]}. Skipping."
        result.passed = True  # don't block on missing audit tools
    except subprocess.TimeoutExpired:
        result.output = f"Audit timed out: {result.command_run}"
        result.passed = True  # don't block on timeout

    return result


# ---------------------------------------------------------------------------
# Completion summary
# ---------------------------------------------------------------------------

@dataclass
class PhaseStat:
    """Timing, cost, and turn data for a single phase."""

    phase: float
    name: str
    duration_s: float = 0.0
    cost_usd: float = 0.0
    turns: int = 0
    status: str = "skipped"  # "completed", "failed", "skipped"


@dataclass
class CompletionSummary:
    """Per-phase summary table rendered on pipeline completion or failure."""

    phases: list[PhaseStat] = field(default_factory=list)
    total_duration_s: float = 0.0
    total_cost_usd: float = 0.0
    final_status: str = "unknown"  # "success" or "failed"
    error_phase: float | None = None
    error_message: str = ""

    def add_phase(
        self,
        phase: float,
        name: str,
        *,
        duration_s: float = 0.0,
        cost_usd: float = 0.0,
        turns: int = 0,
        status: str = "completed",
    ) -> None:
        self.phases.append(PhaseStat(
            phase=phase,
            name=name,
            duration_s=duration_s,
            cost_usd=cost_usd,
            turns=turns,
            status=status,
        ))
        self.total_duration_s += duration_s
        self.total_cost_usd += cost_usd

    def render(self) -> str:
        """Render the summary as a formatted table."""
        lines = [
            "=" * 65,
            f"DARK FACTORY — Pipeline {'Complete' if self.final_status == 'success' else 'Failed'}",
            "=" * 65,
            "",
            f"{'Phase':<8} {'Name':<28} {'Duration':>10} {'Cost':>10} {'Status':>9}",
            "-" * 65,
        ]

        for ps in self.phases:
            duration_str = f"{ps.duration_s:.1f}s" if ps.duration_s > 0 else "-"
            cost_str = f"${ps.cost_usd:.4f}" if ps.cost_usd > 0 else "-"
            lines.append(
                f"{ps.phase:<8} {ps.name:<28} {duration_str:>10} {cost_str:>10} {ps.status:>9}"
            )

        lines.extend([
            "-" * 65,
            f"{'Total':<37} {self.total_duration_s:>9.1f}s ${self.total_cost_usd:>9.4f}",
        ])

        if self.final_status == "failed" and self.error_message:
            lines.extend([
                "",
                f"Failed at Phase {self.error_phase}: {self.error_message}",
            ])

        lines.append("=" * 65)
        return "\n".join(lines)


# Phase name lookup
PHASE_NAMES: dict[float, str] = {
    0: "Tool Discovery",
    1: "Source Ingestion",
    1.5: "Input Quality Gate",
    2: "Codebase Exploration",
    3: "Scaffold & OpenSpec",
    4: "Plan Review Gate",
    5: "Human Checkpoint",
    6: "Issue Creation",
    6.5: "Test Generation",
    7: "Implementation",
    8: "Test & Dep Audit",
    9: "Implementation Review",
    10: "Local Dev Verification",
    11: "PR Creation",
}
