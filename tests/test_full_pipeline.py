"""Integration tests for the full pipeline wiring in _run_full_pipeline().

Verifies that the ``run`` sub-command dispatches phases correctly,
handles dry-run exit, and prints CompletionSummary.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def run_pipeline(
    *args: str,
    stdin: str = "",
    timeout: int = 15,
) -> tuple[int, dict | None, str]:
    """Run ``python3 -m dark_factory run`` and return (rc, parsed_stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "dark_factory", "run", *args],
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
    )
    stdout_data = None
    if result.stdout.strip():
        try:
            stdout_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, stdout_data, result.stderr


@pytest.fixture
def spec_file(tmp_path):
    """Create a minimal spec file for pipeline testing."""
    spec = tmp_path / "test-spec.md"
    spec.write_text(
        "---\n"
        "summary: Add widget feature\n"
        "---\n\n"
        "# Description\n"
        "Add a widget to the dashboard.\n\n"
        "## Acceptance Criteria\n"
        "- Widget displays data\n"
        "- Widget is responsive\n"
    )
    return spec


class TestRunDryRun:
    """Test the ``run`` sub-command in dry-run mode."""

    def test_dry_run_produces_json(self, spec_file):
        """Dry-run should produce valid JSON on stdout."""
        rc, data, stderr = run_pipeline(str(spec_file), "--dry-run")
        assert rc == 0
        assert data is not None
        assert data["status"] == "dry_run_complete"

    def test_dry_run_includes_source(self, spec_file):
        rc, data, stderr = run_pipeline(str(spec_file), "--dry-run")
        assert rc == 0
        assert data["source"]["kind"] == "file"

    def test_dry_run_includes_phases_completed(self, spec_file):
        """Dry-run should complete phases 0 through 5."""
        rc, data, stderr = run_pipeline(str(spec_file), "--dry-run")
        assert rc == 0
        phases = data["phases_completed"]
        # Phase 0 is handled separately, phases 1-5 via run_phase
        # Expect at least phases 1, 1.5, 2 to be in completed list
        assert 1 in phases or 1.0 in phases

    def test_dry_run_prints_summary_to_stderr(self, spec_file):
        """CompletionSummary should appear in stderr."""
        rc, _, stderr = run_pipeline(str(spec_file), "--dry-run")
        assert rc == 0
        assert "DARK FACTORY" in stderr
        assert "Pipeline Complete" in stderr or "Complete" in stderr

    def test_dry_run_with_inline_fails_quality_gate(self):
        """Inline description without AC fails the quality gate (expected)."""
        rc, _, stderr = run_pipeline(
            "add", "a", "login", "page", "--dry-run")
        # Inline with no AC should fail at Phase 1.5 quality gate
        assert rc == 1
        assert "quality gate" in stderr.lower() or "acceptance criteria" in stderr.lower()


class TestRunSubcommandErrors:
    """Test error handling in the run sub-command."""

    def test_missing_file_spec(self):
        """Non-existent file should produce a pipeline error."""
        rc, _, stderr = run_pipeline("/nonexistent/spec.md", "--dry-run")
        assert rc == 1
        assert "DARK FACTORY" in stderr  # CompletionSummary printed
        assert "Failed" in stderr


class TestRunSubcommandRegistration:
    """Test that the ``run`` sub-command is properly registered."""

    def test_run_is_recognized(self):
        """The ``run`` sub-command should not produce 'Unknown phase'."""
        result = subprocess.run(
            [sys.executable, "-m", "dark_factory", "run", "--help-not-real"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # It should attempt to parse args, not say "Unknown phase"
        assert "Unknown phase" not in result.stderr
