"""Tests for batch-implemented features:
- Cost circuit breaker (cg3)
- Phase 7 checkpointing (8w8)
- Sprint contracts (13k)
- Review calibration (4lt)
- JSONL task events (9yb.1)
- Internal ID generation (9yb.2) — covered in test_issues.py
- Beads removal from Phase 7 (9yb.3)
- Draft PR (9yb.5)
- Beads removal from Phase 11 (9yb.6) — covered in test_pr.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dark_factory.cli import parse_args
from dark_factory.pipeline import (
    REVIEW_CALIBRATION,
    Phase6_75Result,
    SprintContract,
    _build_phase7_prompt,
    _log_task_event,
)
from dark_factory.state import PipelineState, SourceInfo


def _make_state(tmp_path: Path) -> PipelineState:
    source = SourceInfo(kind="inline", raw="test", id="test")
    return PipelineState(source=source, repo_root=str(tmp_path))


class TestCostCircuitBreaker:
    def test_max_cost_usd_default_none(self, tmp_path):
        state = _make_state(tmp_path)
        assert state.max_cost_usd is None

    def test_max_cost_usd_roundtrip(self, tmp_path):
        state = _make_state(tmp_path)
        state.max_cost_usd = 50.0
        path = state.save()
        loaded = PipelineState.load(path)
        assert loaded.max_cost_usd == 50.0

    def test_cli_max_cost_flag(self):
        args = parse_args(["SDLC-1", "--max-cost", "25.0"])
        assert args.max_cost == 25.0

    def test_cli_max_cost_equals(self):
        args = parse_args(["SDLC-1", "--max-cost=100"])
        assert args.max_cost == 100.0

    def test_cli_no_max_cost(self):
        args = parse_args(["SDLC-1"])
        assert args.max_cost is None


class TestPhase7Checkpointing:
    def test_completed_tasks_default_empty(self, tmp_path):
        state = _make_state(tmp_path)
        assert state.phase7_completed_tasks == []

    def test_completed_tasks_roundtrip(self, tmp_path):
        state = _make_state(tmp_path)
        state.phase7_completed_tasks = ["TASK-1", "TASK-3"]
        path = state.save()
        loaded = PipelineState.load(path)
        assert loaded.phase7_completed_tasks == ["TASK-1", "TASK-3"]


class TestSprintContracts:
    def test_sprint_contract_dataclass(self):
        c = SprintContract(task_id="T-1", task_title="Add caching")
        assert c.approach == ""
        assert c.acceptance_criteria == []

    def test_phase_6_75_result(self):
        r = Phase6_75Result()
        assert r.contracts == []
        assert r.cost_usd == 0.0
        assert r.validated is False

    def test_state_sprint_contracts_roundtrip(self, tmp_path):
        state = _make_state(tmp_path)
        state.sprint_contracts = [
            {"task_id": "T-1", "approach": "use cache", "verification": "test it",
             "acceptance_criteria": ["passes tests"]}
        ]
        path = state.save()
        loaded = PipelineState.load(path)
        assert len(loaded.sprint_contracts) == 1
        assert loaded.sprint_contracts[0]["task_id"] == "T-1"

    def test_phase_routing_6_5_to_6_75(self, tmp_path):
        from dark_factory.pipeline import run_phase

        state = _make_state(tmp_path)
        state.current_phase = 6.5
        state.completed_phases = [0, 1, 2, 3, 4, 5, 6]

        async def noop():
            return None

        asyncio.run(run_phase(state, 6.5, noop))
        assert state.current_phase == 6.75

    def test_phase_routing_6_75_to_7(self, tmp_path):
        from dark_factory.pipeline import run_phase

        state = _make_state(tmp_path)
        state.current_phase = 6.75
        state.completed_phases = [0, 1, 2, 3, 4, 5, 6, 6.5]

        async def noop():
            return None

        asyncio.run(run_phase(state, 6.75, noop))
        assert state.current_phase == 7

    def test_build_prompt_with_contract(self):
        contract = {
            "approach": "Add Redis cache layer",
            "verification": "Run integration tests",
            "acceptance_criteria": ["Cache hit rate > 90%", "TTL configurable"],
        }
        prompt = _build_phase7_prompt("/tmp/wt", "T-1", "Add caching",
                                      sprint_contract=contract)
        assert "Sprint Contract" in prompt
        assert "Add Redis cache layer" in prompt
        assert "Cache hit rate > 90%" in prompt

    def test_build_prompt_without_contract(self):
        prompt = _build_phase7_prompt("/tmp/wt", "T-1", "Add caching")
        assert "Sprint Contract" not in prompt


class TestReviewCalibration:
    def test_calibration_has_5_examples(self):
        assert REVIEW_CALIBRATION.count("### Example") == 5

    def test_calibration_has_pass_examples(self):
        assert "Verdict: PASS" in REVIEW_CALIBRATION

    def test_calibration_has_needs_fix_examples(self):
        assert "Verdict: NEEDS_FIX" in REVIEW_CALIBRATION

    def test_calibration_includes_false_positive(self):
        assert "looks suspicious" in REVIEW_CALIBRATION.lower() or \
               "looks like a bug" in REVIEW_CALIBRATION.lower()

    def test_calibration_includes_security_issue(self):
        assert "SQL injection" in REVIEW_CALIBRATION


class TestTaskLevelEvents:
    def test_log_task_event_writes_jsonl(self, tmp_path):
        state = _make_state(tmp_path)
        _log_task_event(state, "task_start", task_id="T-1", task_title="Do thing")

        events_path = tmp_path / ".dark-factory" / "test.events.jsonl"
        assert events_path.exists()

        lines = events_path.read_text().strip().splitlines()
        assert len(lines) == 1

        event = json.loads(lines[0])
        assert event["event_type"] == "task_start"
        assert event["task_id"] == "T-1"
        assert event["task_title"] == "Do thing"
        assert "timestamp" in event

    def test_log_task_event_wave(self, tmp_path):
        state = _make_state(tmp_path)
        _log_task_event(state, "wave_start", wave=2)
        _log_task_event(state, "wave_complete", wave=2)

        events_path = tmp_path / ".dark-factory" / "test.events.jsonl"
        lines = events_path.read_text().strip().splitlines()
        assert len(lines) == 2

        e1 = json.loads(lines[0])
        assert e1["event_type"] == "wave_start"
        assert e1["wave"] == 2

    def test_log_task_event_omits_null_fields(self, tmp_path):
        state = _make_state(tmp_path)
        _log_task_event(state, "task_skipped", task_id="T-5")

        events_path = tmp_path / ".dark-factory" / "test.events.jsonl"
        event = json.loads(events_path.read_text().strip())
        assert "wave" not in event
        assert "success" not in event
        assert "duration_ms" not in event

    def test_log_task_event_success_field(self, tmp_path):
        state = _make_state(tmp_path)
        _log_task_event(state, "task_complete", task_id="T-1", success=True)

        events_path = tmp_path / ".dark-factory" / "test.events.jsonl"
        event = json.loads(events_path.read_text().strip())
        assert event["success"] is True


class TestDraftPr:
    def test_draft_pr_url_default_empty(self, tmp_path):
        state = _make_state(tmp_path)
        assert state.draft_pr_url == ""

    def test_draft_pr_url_roundtrip(self, tmp_path):
        state = _make_state(tmp_path)
        state.draft_pr_url = "https://github.com/org/repo/pull/42"
        path = state.save()
        loaded = PipelineState.load(path)
        assert loaded.draft_pr_url == "https://github.com/org/repo/pull/42"
