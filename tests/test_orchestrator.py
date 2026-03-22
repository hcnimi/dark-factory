"""Tests for dark_factory.orchestrator: diff guard, dep audit, summary."""

from __future__ import annotations

import subprocess

import pytest

from dark_factory.orchestrator import (
    AuditResult,
    CompletionSummary,
    DiffSizeReport,
    PhaseStat,
    PHASE_NAMES,
    _parse_diff_stat_total,
    dependency_audit,
    detect_project_type,
    diff_size_guard,
)


# ---------------------------------------------------------------------------
# Diff-size guard
# ---------------------------------------------------------------------------

class TestParseDiffStatTotal:
    def test_typical_line(self):
        line = " 5 files changed, 120 insertions(+), 30 deletions(-)"
        assert _parse_diff_stat_total(line) == 150

    def test_insertions_only(self):
        line = " 3 files changed, 45 insertions(+)"
        assert _parse_diff_stat_total(line) == 45

    def test_deletions_only(self):
        line = " 2 files changed, 10 deletions(-)"
        assert _parse_diff_stat_total(line) == 10

    def test_empty_line(self):
        assert _parse_diff_stat_total("") == 0

    def test_no_numbers(self):
        assert _parse_diff_stat_total("no changes") == 0


class TestDiffSizeGuard:
    def test_dry_run(self):
        report = diff_size_guard("/tmp", task_count=5, dry_run=True)
        assert report.passed is True
        assert report.actual_lines == 0
        assert report.expected_lines == 750  # 5 * 150

    def test_expected_lines_calculation(self):
        report = diff_size_guard("/tmp", task_count=3, dry_run=True)
        assert report.expected_lines == 450

    def test_zero_tasks(self):
        report = diff_size_guard("/tmp", task_count=0, dry_run=True)
        assert report.expected_lines == 0
        assert report.passed is True


class TestDiffSizeReport:
    def test_passes_under_threshold(self):
        report = DiffSizeReport(
            actual_lines=400,
            expected_lines=450,
        )
        report.ratio = 400 / 450
        assert report.ratio < DiffSizeReport.WARN_THRESHOLD
        assert report.passed is True

    def test_warning_over_threshold(self):
        report = DiffSizeReport(
            actual_lines=2000,
            expected_lines=450,
            passed=False,
        )
        report.ratio = 2000 / 450
        assert report.ratio > DiffSizeReport.WARN_THRESHOLD

    def test_constants(self):
        assert DiffSizeReport.LINES_PER_TASK == 150
        assert DiffSizeReport.WARN_THRESHOLD == 3.0


# ---------------------------------------------------------------------------
# Dependency audit
# ---------------------------------------------------------------------------

class TestDetectProjectType:
    def test_node(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert detect_project_type(str(tmp_path)) == "node"

    def test_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        assert detect_project_type(str(tmp_path)) == "python"

    def test_python_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("")
        assert detect_project_type(str(tmp_path)) == "python"

    def test_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/foo")
        assert detect_project_type(str(tmp_path)) == "go"

    def test_unknown(self, tmp_path):
        assert detect_project_type(str(tmp_path)) == ""


class TestDependencyAudit:
    def test_no_project_type(self, tmp_path):
        result = dependency_audit(str(tmp_path))
        assert result.passed is True
        assert "No recognized project type" in result.output

    def test_dry_run_node(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        result = dependency_audit(str(tmp_path), dry_run=True)
        assert result.project_type == "node"
        assert "dry-run" in result.output

    def test_dry_run_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        result = dependency_audit(str(tmp_path), dry_run=True)
        assert result.project_type == "python"
        assert "dry-run" in result.output

    def test_dry_run_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("module test")
        result = dependency_audit(str(tmp_path), dry_run=True)
        assert result.project_type == "go"
        assert "dry-run" in result.output

    def test_result_fields(self):
        r = AuditResult(
            project_type="node",
            command_run="npm audit",
            passed=True,
            output="ok",
            vulnerabilities=0,
        )
        assert r.project_type == "node"
        assert r.passed is True


# ---------------------------------------------------------------------------
# Completion summary
# ---------------------------------------------------------------------------

class TestPhaseStat:
    def test_fields(self):
        ps = PhaseStat(
            phase=7,
            name="Implementation",
            duration_s=45.3,
            cost_usd=2.50,
            turns=30,
            status="completed",
        )
        assert ps.phase == 7
        assert ps.duration_s == 45.3

    def test_default_status(self):
        ps = PhaseStat(phase=0, name="Init")
        assert ps.status == "skipped"


class TestCompletionSummary:
    def test_add_phase(self):
        summary = CompletionSummary()
        summary.add_phase(0, "Tool Discovery", duration_s=0.5, cost_usd=0.0)
        summary.add_phase(7, "Implementation", duration_s=45.0, cost_usd=2.5)
        assert len(summary.phases) == 2
        assert summary.total_duration_s == pytest.approx(45.5)
        assert summary.total_cost_usd == pytest.approx(2.5)

    def test_render_success(self):
        summary = CompletionSummary()
        summary.final_status = "success"
        summary.add_phase(0, "Tool Discovery", duration_s=0.1)
        summary.add_phase(7, "Implementation", duration_s=30.0, cost_usd=1.5)
        output = summary.render()
        assert "Complete" in output
        assert "Tool Discovery" in output
        assert "Implementation" in output
        assert "Total" in output

    def test_render_failure(self):
        summary = CompletionSummary()
        summary.final_status = "failed"
        summary.error_phase = 8
        summary.error_message = "Tests failed after 2 retries"
        summary.add_phase(0, "Tool Discovery", duration_s=0.1)
        summary.add_phase(8, "Test Verification", duration_s=60.0, status="failed")
        output = summary.render()
        assert "Failed" in output
        assert "Phase 8" in output
        assert "Tests failed" in output

    def test_render_with_costs(self):
        summary = CompletionSummary()
        summary.final_status = "success"
        summary.add_phase(3, "Scaffold", duration_s=5.0, cost_usd=0.05)
        summary.add_phase(7, "Implementation", duration_s=30.0, cost_usd=2.0)
        summary.add_phase(9, "Review", duration_s=10.0, cost_usd=0.5)
        output = summary.render()
        assert "$" in output

    def test_render_empty(self):
        summary = CompletionSummary()
        summary.final_status = "success"
        output = summary.render()
        assert "Complete" in output
        assert "Total" in output

    def test_phase_with_zero_duration(self):
        summary = CompletionSummary()
        summary.add_phase(5, "Checkpoint", duration_s=0.0)
        output = summary.render()
        assert "-" in output  # zero duration shows as "-"


class TestPhaseNames:
    def test_all_phases_named(self):
        for phase in range(12):
            assert phase in PHASE_NAMES, f"Phase {phase} missing from PHASE_NAMES"

    def test_phase_7_is_implementation(self):
        assert PHASE_NAMES[7] == "Implementation"

    def test_phase_8_includes_audit(self):
        assert "Audit" in PHASE_NAMES[8]
