"""Round-trip tests for dark_factory.state: ALL fields preserved through save/load.

Focuses on edge cases: empty fields, None values, large phase_timings maps,
unusual source kinds, and state mutation between saves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dark_factory.state import PipelineError, PipelineState, SourceInfo


# ---------------------------------------------------------------------------
# SourceInfo edge cases
# ---------------------------------------------------------------------------

class TestSourceInfoEdgeCases:
    def test_inline_source(self):
        s = SourceInfo(kind="inline", raw="add dark mode toggle", id="add-dark-mode-toggle")
        assert s.kind == "inline"
        assert s.raw == "add dark mode toggle"

    def test_source_with_special_chars_in_raw(self):
        s = SourceInfo(kind="inline", raw="add OAuth2.0 & SSO", id="add-oauth2-0-sso")
        assert "&" in s.raw

    def test_source_with_empty_id(self):
        s = SourceInfo(kind="inline", raw="", id="")
        assert s.id == ""


# ---------------------------------------------------------------------------
# Round-trip: ALL fields preserved
# ---------------------------------------------------------------------------

class TestRoundTripAllFields:
    """Every field on PipelineState must survive save() -> load()."""

    def test_all_fields_preserved(self, tmp_path):
        source = SourceInfo(kind="jira", raw="SDLC-123", id="sdlc-123")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=5,
            completed_phases=[0, 1, 2, 3, 4],
            worktree_path="/tmp/wt/sdlc-123",
            branch="feat/sdlc-123",
            epic_id="EPIC-42",
            issues=[
                {"id": "SDLC-124", "title": "subtask 1", "type": "task"},
                {"id": "SDLC-125", "title": "subtask 2", "type": "task"},
            ],
            phase_timings={
                "0": 0.123,
                "1": 1.456,
                "2": 2.789,
                "3": 10.5,
                "4": 0.001,
            },
            total_cost_usd=3.14,
            dry_run=True,
            error="Phase 4 had a warning",
        )

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.source.kind == source.kind
        assert loaded.source.raw == source.raw
        assert loaded.source.id == source.id
        assert loaded.current_phase == 5
        assert loaded.completed_phases == [0, 1, 2, 3, 4]
        assert loaded.worktree_path == "/tmp/wt/sdlc-123"
        assert loaded.branch == "feat/sdlc-123"
        assert loaded.epic_id == "EPIC-42"
        assert len(loaded.issues) == 2
        assert loaded.issues[0]["id"] == "SDLC-124"
        assert loaded.issues[1]["title"] == "subtask 2"
        assert loaded.phase_timings == {
            "0": 0.123,
            "1": 1.456,
            "2": 2.789,
            "3": 10.5,
            "4": 0.001,
        }
        assert loaded.total_cost_usd == pytest.approx(3.14)
        assert loaded.dry_run is True
        assert loaded.error == "Phase 4 had a warning"

    def test_default_fields_preserved(self, tmp_path):
        """A fresh state with defaults must round-trip cleanly."""
        source = SourceInfo(kind="file", raw="spec.md", id="spec")
        state = PipelineState(source=source, repo_root=str(tmp_path))

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.current_phase == 0
        assert loaded.completed_phases == []
        assert loaded.worktree_path == ""
        assert loaded.branch == ""
        assert loaded.epic_id is None
        assert loaded.issues == []
        assert loaded.phase_timings == {}
        assert loaded.total_cost_usd == 0.0
        assert loaded.dry_run is False
        assert loaded.error is None

    def test_phase_timings_many_phases(self, tmp_path):
        """All 12 phases timed must survive round-trip."""
        source = SourceInfo(kind="jira", raw="TEST-1", id="test-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        for i in range(12):
            state.phase_timings[str(i)] = float(i) * 1.1
            state.completed_phases.append(i)

        path = state.save()
        loaded = PipelineState.load(path)

        assert len(loaded.phase_timings) == 12
        for i in range(12):
            assert loaded.phase_timings[str(i)] == pytest.approx(float(i) * 1.1)
        assert loaded.completed_phases == list(range(12))

    def test_phase_timings_sub_millisecond(self, tmp_path):
        """Very small timing values must not be lost to rounding."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        state.phase_timings["0"] = 0.001
        state.phase_timings["1"] = 0.0005

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.phase_timings["0"] == pytest.approx(0.001)
        assert loaded.phase_timings["1"] == pytest.approx(0.0005)


# ---------------------------------------------------------------------------
# Mutation between saves
# ---------------------------------------------------------------------------

class TestStateMutation:
    def test_incremental_save_preserves_earlier_data(self, tmp_path):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))

        # Save after phase 0
        state.current_phase = 1
        state.completed_phases.append(0)
        state.phase_timings["0"] = 0.5
        state.save()

        # Save after phase 1
        state.current_phase = 2
        state.completed_phases.append(1)
        state.phase_timings["1"] = 1.2
        path = state.save()

        loaded = PipelineState.load(path)
        assert loaded.completed_phases == [0, 1]
        assert loaded.phase_timings["0"] == 0.5
        assert loaded.phase_timings["1"] == 1.2
        assert loaded.current_phase == 2

    def test_error_then_clear_then_save(self, tmp_path):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))

        state.error = "something failed"
        state.save()

        # Clear error on resume
        state.error = None
        path = state.save()

        loaded = PipelineState.load(path)
        assert loaded.error is None

    def test_issues_list_grows(self, tmp_path):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))

        state.issues.append({"id": "T-2", "title": "first"})
        state.save()
        state.issues.append({"id": "T-3", "title": "second"})
        path = state.save()

        loaded = PipelineState.load(path)
        assert len(loaded.issues) == 2


# ---------------------------------------------------------------------------
# JSON file structure
# ---------------------------------------------------------------------------

class TestStateFileStructure:
    def test_json_structure_matches_fields(self, tmp_path):
        source = SourceInfo(kind="inline", raw="test desc", id="test-desc")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        state.phase_timings["0"] = 0.42
        state.total_cost_usd = 1.5

        path = state.save()
        data = json.loads(path.read_text())

        # Top-level keys must match dataclass fields
        expected_keys = {
            "source", "repo_root", "current_phase", "completed_phases",
            "worktree_path", "branch", "draft_pr_url", "epic_id", "issues",
            "phase_timings", "total_cost_usd", "max_cost_usd", "dry_run",
            "error", "visible_test_paths", "holdout_test_paths",
            "max_parallel", "sprint_contracts",
            "pipeline_status", "updated_at", "phase7_progress",
            "phase7_completed_tasks", "run_id",
        }
        assert set(data.keys()) == expected_keys

        # Nested source
        assert set(data["source"].keys()) == {"kind", "raw", "id"}
        assert data["source"]["kind"] == "inline"

        # Types preserved
        assert isinstance(data["phase_timings"], dict)
        assert isinstance(data["total_cost_usd"], float)
        assert isinstance(data["completed_phases"], list)

    def test_state_file_path_uses_source_id(self, tmp_path):
        source = SourceInfo(kind="jira", raw="PROJ-42", id="proj-42")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        path = state.save()
        assert path.name == "proj-42.json"
        assert path.parent.name == ".dark-factory"

    def test_state_file_pretty_printed(self, tmp_path):
        """JSON should be indented for human readability."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        path = state.save()
        content = path.read_text()
        # Indented JSON has newlines and leading spaces
        assert "\n" in content
        assert "  " in content


# ---------------------------------------------------------------------------
# PipelineState helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:
    def test_next_phase_after_resume(self, tmp_path):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        state.current_phase = 7
        state.completed_phases = [0, 1, 2, 3, 4, 5, 6]

        # next_phase returns current_phase (where to resume)
        assert state.next_phase() == 7

    def test_is_phase_completed_boundary(self, tmp_path):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(tmp_path))
        state.completed_phases = [0, 1, 2]

        assert state.is_phase_completed(0) is True
        assert state.is_phase_completed(2) is True
        assert state.is_phase_completed(3) is False
        assert state.is_phase_completed(11) is False
        assert state.is_phase_completed(-1) is False
