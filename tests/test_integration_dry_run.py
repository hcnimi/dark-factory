"""Integration test: dry-run pipeline against a test repo.

Runs the core pipeline mechanics (parse -> state -> phase runner -> save)
in dry-run mode, then verifies the JSON state file contents and phase timing
entries. Does NOT invoke the Claude SDK.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from dark_factory.cli import parse_args
from dark_factory.explore import prefetch_context
from dark_factory.ingest import TicketFields, ingest_file
from dark_factory.pipeline import run_phase
from dark_factory.state import PipelineState, PipelineError, SourceInfo


@pytest.fixture
def integration_repo(tmp_path):
    """A realistic repo for integration testing."""
    repo = tmp_path / "integration-repo"
    repo.mkdir()

    # package.json
    (repo / "package.json").write_text(json.dumps({
        "name": "integration-test",
        "scripts": {"test": "jest", "lint": "eslint ."},
        "dependencies": {"express": "^4.18.0"},
        "devDependencies": {"jest": "^29.0.0"},
    }))

    # Source
    src = repo / "src"
    src.mkdir()
    (src / "index.ts").write_text("export function main() { console.log('hello'); }\n")

    # Spec file
    specs = repo / "specs"
    specs.mkdir()
    (specs / "dark-mode.md").write_text(
        "---\n"
        "summary: Add dark mode toggle\n"
        "labels: [frontend, ux]\n"
        "---\n\n"
        "# Description\n"
        "Add a toggle for dark mode in settings.\n\n"
        "## Acceptance Criteria\n"
        "- Toggle visible in settings\n"
        "- Preference persists across sessions\n"
    )

    # CI
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\n")

    # Convention files
    (repo / "CLAUDE.md").write_text("# Rules\nRun tests before commit.\n")

    # Git init
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
         "commit", "-m", "initial commit"],
        cwd=str(repo), capture_output=True,
    )

    return repo


# ---------------------------------------------------------------------------
# Integration: Jira key dry-run pipeline
# ---------------------------------------------------------------------------

class TestDryRunPipelineJira:
    """Simulate a Jira-based pipeline run in dry-run mode."""

    def test_full_pipeline_state_lifecycle(self, integration_repo):
        # Phase 0: Parse args
        parsed = parse_args(["SDLC-42", "--dry-run"])
        assert parsed.source.kind == "jira"
        assert parsed.dry_run is True

        # Create state
        state = PipelineState(
            source=parsed.source,
            repo_root=str(integration_repo),
            dry_run=True,
        )

        # Phase 0: tool discovery (simulated)
        async def phase_0():
            return {"tools_available": True, "missing": parsed.missing_tools}

        result_0 = asyncio.run(run_phase(state, 0, phase_0))
        assert result_0["tools_available"] is True
        assert state.current_phase == 1
        assert 0 in state.completed_phases
        assert "0" in state.phase_timings

        # Phase 1: ingestion (dry-run, no Jira)
        async def phase_1():
            return TicketFields(
                summary="Add dark mode toggle",
                description="Dark mode for settings",
                acceptance_criteria=["Toggle visible", "Persists"],
            )

        result_1 = asyncio.run(run_phase(state, 1, phase_1))
        assert result_1.summary == "Add dark mode toggle"
        assert state.current_phase == 1.5
        assert "1" in state.phase_timings

        # Phase 1.5: input quality gate (simulated noop for integration test)
        async def phase_1_5():
            return None

        asyncio.run(run_phase(state, 1.5, phase_1_5))
        assert state.current_phase == 2
        assert "1.5" in state.phase_timings

        # Phase 2a: context pre-fetch
        async def phase_2():
            return prefetch_context(str(integration_repo), ticket=result_1)

        result_2 = asyncio.run(run_phase(state, 2, phase_2))
        assert result_2.repo_root == str(integration_repo)
        assert state.current_phase == 3
        assert "2" in state.phase_timings

        # Verify state file on disk
        state_path = Path(integration_repo) / ".dark-factory" / "sdlc-42.json"
        assert state_path.exists()

        data = json.loads(state_path.read_text())
        assert data["source"]["kind"] == "jira"
        assert data["source"]["id"] == "sdlc-42"
        assert data["current_phase"] == 3
        assert data["completed_phases"] == [0, 1, 1.5, 2]
        assert data["dry_run"] is True
        assert len(data["phase_timings"]) == 4
        # All timings should be non-negative
        for phase_key, timing in data["phase_timings"].items():
            assert timing >= 0, f"Phase {phase_key} timing should be >= 0"

    def test_state_round_trips_after_pipeline(self, integration_repo):
        """Load the state file and verify it matches the live state."""
        parsed = parse_args(["TEST-99", "--dry-run"])
        state = PipelineState(
            source=parsed.source,
            repo_root=str(integration_repo),
            dry_run=True,
        )

        async def noop():
            return None

        asyncio.run(run_phase(state, 0, noop))
        asyncio.run(run_phase(state, 1, noop))

        state_path = state._state_path()
        loaded = PipelineState.load(state_path)

        assert loaded.source.kind == state.source.kind
        assert loaded.source.id == state.source.id
        assert loaded.current_phase == state.current_phase
        assert loaded.completed_phases == state.completed_phases
        assert loaded.dry_run == state.dry_run
        assert set(loaded.phase_timings.keys()) == set(state.phase_timings.keys())


# ---------------------------------------------------------------------------
# Integration: File-based pipeline
# ---------------------------------------------------------------------------

class TestDryRunPipelineFile:
    def test_file_input_pipeline(self, integration_repo):
        spec_path = str(integration_repo / "specs" / "dark-mode.md")
        parsed = parse_args([spec_path, "--dry-run"])
        # Contains "/" so classified as file
        assert parsed.source.kind == "file"
        assert parsed.dry_run is True

        state = PipelineState(
            source=parsed.source,
            repo_root=str(integration_repo),
            dry_run=True,
        )

        # Phase 1: file ingestion
        async def phase_1():
            return ingest_file(spec_path)

        result_1 = asyncio.run(run_phase(state, 1, phase_1))
        assert result_1.summary == "Add dark mode toggle"
        assert result_1.labels == ["frontend", "ux"]
        assert len(result_1.acceptance_criteria) == 2

        # Phase 2: prefetch
        async def phase_2():
            return prefetch_context(str(integration_repo), ticket=result_1)

        result_2 = asyncio.run(run_phase(state, 2, phase_2))
        assert result_2.project_metadata.get("package_json", {}).get("name") == "integration-test"
        assert ".github/workflows/ci.yml" in result_2.ci_configs

        # Verify state file
        state_path = state._state_path()
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["completed_phases"] == [1, 2]
        assert data["current_phase"] == 3


# ---------------------------------------------------------------------------
# Integration: Inline description pipeline
# ---------------------------------------------------------------------------

class TestDryRunPipelineInline:
    def test_inline_input_pipeline(self, integration_repo):
        parsed = parse_args(["add", "dark", "mode", "toggle", "--dry-run"])
        assert parsed.source.kind == "inline"
        assert parsed.source.raw == "add dark mode toggle"
        assert parsed.dry_run is True

        state = PipelineState(
            source=parsed.source,
            repo_root=str(integration_repo),
            dry_run=True,
        )

        # Simulate phases
        async def phase_0():
            return {"tools": "ok"}

        async def phase_1():
            # In dry-run, inline ingestion returns minimal fields
            return TicketFields(
                summary="add dark mode toggle",
                description="add dark mode toggle",
            )

        asyncio.run(run_phase(state, 0, phase_0))
        asyncio.run(run_phase(state, 1, phase_1))

        state_path = state._state_path()
        data = json.loads(state_path.read_text())
        assert data["source"]["kind"] == "inline"
        assert data["source"]["raw"] == "add dark mode toggle"
        assert data["completed_phases"] == [0, 1]


# ---------------------------------------------------------------------------
# Integration: failure recovery
# ---------------------------------------------------------------------------

class TestDryRunPipelineFailure:
    def test_failure_preserves_state_for_resume(self, integration_repo):
        parsed = parse_args(["FAIL-1", "--dry-run"])
        state = PipelineState(
            source=parsed.source,
            repo_root=str(integration_repo),
            dry_run=True,
        )

        async def noop():
            return None

        async def failing_phase():
            raise RuntimeError("Phase 2 timed out")

        # Phase 0, 1, and 1.5 succeed
        asyncio.run(run_phase(state, 0, noop))
        asyncio.run(run_phase(state, 1, noop))
        asyncio.run(run_phase(state, 1.5, noop))

        # Phase 2 fails
        with pytest.raises(PipelineError) as exc_info:
            asyncio.run(run_phase(state, 2, failing_phase))
        assert exc_info.value.phase == 2

        # State preserved on disk for resume
        state_path = state._state_path()
        data = json.loads(state_path.read_text())
        assert data["completed_phases"] == [0, 1, 1.5]
        assert data["current_phase"] == 2  # stuck at failed phase
        assert data["error"] == "Phase 2 timed out"
        assert "2" in data["phase_timings"]  # timing recorded even on failure

    def test_resume_after_failure(self, integration_repo):
        """Simulate loading state from a failed run and resuming."""
        # Create initial failed state
        source = SourceInfo(kind="jira", raw="RESUME-1", id="resume-1")
        state = PipelineState(
            source=source,
            repo_root=str(integration_repo),
            current_phase=3,
            completed_phases=[0, 1, 2],
            phase_timings={"0": 0.1, "1": 0.5, "2": 1.2},
            error="Phase 3 failed: timeout",
            dry_run=True,
        )
        path = state.save()

        # Load and resume
        loaded = PipelineState.load(path)
        assert loaded.next_phase() == 3
        assert loaded.error == "Phase 3 failed: timeout"

        # Clear error and continue
        loaded.error = None

        async def phase_3():
            return "recovered"

        result = asyncio.run(run_phase(loaded, 3, phase_3))
        assert result == "recovered"

        # Verify state updated
        reloaded = PipelineState.load(path)
        assert reloaded.current_phase == 4
        assert reloaded.completed_phases == [0, 1, 2, 3]
        assert reloaded.error is None
        assert "3" in reloaded.phase_timings


# ---------------------------------------------------------------------------
# Integration: phase timing precision
# ---------------------------------------------------------------------------

class TestPhaseTimingPrecision:
    def test_timing_values_are_positive(self, integration_repo):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(integration_repo))

        async def noop():
            return None

        for i in range(5):
            asyncio.run(run_phase(state, i, noop))

        for key, value in state.phase_timings.items():
            assert value >= 0, f"Phase {key} timing should be >= 0"

    def test_timing_stored_as_float_in_json(self, integration_repo):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(integration_repo))

        async def noop():
            return None

        asyncio.run(run_phase(state, 0, noop))

        data = json.loads(state._state_path().read_text())
        assert isinstance(data["phase_timings"]["0"], float)

    def test_many_phases_all_timed(self, integration_repo):
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(source=source, repo_root=str(integration_repo))

        async def noop():
            return None

        for i in range(10):
            asyncio.run(run_phase(state, i, noop))

        assert len(state.phase_timings) == 10
        data = json.loads(state._state_path().read_text())
        assert len(data["phase_timings"]) == 10
        assert data["completed_phases"] == list(range(10))
        assert data["current_phase"] == 10
