"""Integration tests — exercise _run_pipeline with mocked SDK calls."""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from dark_factory.__main__ import _run_pipeline
from dark_factory.types import (
    CriterionAssessment,
    CriterionStatus,
    DarkFactoryError,
    DimensionScore,
    EvaluationReport,
    Gate,
    IntentDocument,
    RunConfig,
    RunState,
    RunStatus,
    SourceInfo,
    SourceKind,
)


def _make_intent():
    return IntentDocument(
        title="Add Feature X",
        summary="Adds feature X to the system",
        acceptance_criteria=["AC1: endpoint exists", "AC2: returns 200"],
    )


def _make_report(cost=0.05):
    return EvaluationReport(
        scores=[
            DimensionScore("Intent Fidelity", 9, "good"),
            DimensionScore("Correctness", 8, "solid"),
            DimensionScore("Integration", 9, "clean"),
        ],
        criteria=[
            CriterionAssessment("AC1", CriterionStatus.MET, "found"),
            CriterionAssessment("AC2", CriterionStatus.MET, "found"),
        ],
        model_used="sonnet",
        cost_usd=cost,
    )


def _make_state(tmp_path, gates=None):
    source = SourceInfo(SourceKind.INLINE, "add feature x", "add-feature-x")
    config = RunConfig(gates=gates or [])
    state = RunState.create(source=source, config=config)
    state.state_dir(str(tmp_path))  # Create .dark-factory dir
    return state


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_full_flow_no_gates(self, tmp_path):
        """Full pipeline: intent -> implement -> evaluate, no gates."""
        state = _make_state(tmp_path)
        intent = _make_intent()
        report = _make_report()

        mock_clarify = AsyncMock(return_value=intent)
        mock_implement = AsyncMock(return_value="diff content here")
        mock_evaluate = AsyncMock(return_value=report)

        await _run_pipeline(
            state, str(tmp_path),
            mock_clarify, mock_implement, mock_evaluate,
        )

        assert state.status == RunStatus.COMPLETE
        assert state.intent == intent
        assert state.evaluation == report
        assert state.cost_usd == report.cost_usd
        mock_clarify.assert_awaited_once()
        mock_implement.assert_awaited_once()
        mock_evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_state_saved_after_each_phase(self, tmp_path):
        """State is saved to disk at each transition."""
        state = _make_state(tmp_path)

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(return_value="diff")
        mock_evaluate = AsyncMock(return_value=_make_report())

        await _run_pipeline(
            state, str(tmp_path),
            mock_clarify, mock_implement, mock_evaluate,
        )

        # State file should exist and reflect completion
        state_path = state.state_path(str(tmp_path))
        assert state_path.exists()
        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "complete"

    @pytest.mark.asyncio
    async def test_events_logged(self, tmp_path):
        """JSONL events are logged throughout the pipeline."""
        state = _make_state(tmp_path)

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(return_value="diff")
        mock_evaluate = AsyncMock(return_value=_make_report())

        await _run_pipeline(
            state, str(tmp_path),
            mock_clarify, mock_implement, mock_evaluate,
        )

        events_path = state.events_path(str(tmp_path))
        assert events_path.exists()
        events = [json.loads(l) for l in events_path.read_text().strip().splitlines()]
        event_types = [e["type"] for e in events]
        assert "intent_complete" in event_types
        assert "implementation_started" in event_types
        assert "implementation_complete" in event_types
        assert "evaluation_complete" in event_types
        assert "run_complete" in event_types

    @pytest.mark.asyncio
    async def test_evaluation_report_saved(self, tmp_path):
        """Evaluation JSON report is written to disk."""
        state = _make_state(tmp_path)

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(return_value="diff")
        mock_evaluate = AsyncMock(return_value=_make_report())

        await _run_pipeline(
            state, str(tmp_path),
            mock_clarify, mock_implement, mock_evaluate,
        )

        eval_path = state.evaluation_path(str(tmp_path))
        assert eval_path.exists()
        eval_data = json.loads(eval_path.read_text())
        assert len(eval_data["scores"]) == 3

    @pytest.mark.asyncio
    async def test_intent_gate_abort(self, tmp_path):
        """Intent gate abort raises DarkFactoryError."""
        state = _make_state(tmp_path, gates=[Gate.INTENT])

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock()
        mock_evaluate = AsyncMock()

        with patch("builtins.input", return_value="abort"):
            with pytest.raises(DarkFactoryError, match="aborted by user"):
                await _run_pipeline(
                    state, str(tmp_path),
                    mock_clarify, mock_implement, mock_evaluate,
                )

        # Implementation should NOT have been called
        mock_implement.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_eval_gate_abort(self, tmp_path):
        """Eval gate abort raises DarkFactoryError."""
        state = _make_state(tmp_path, gates=[Gate.EVAL])

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(return_value="diff")
        mock_evaluate = AsyncMock(return_value=_make_report())

        with patch("builtins.input", return_value="quit"):
            with pytest.raises(DarkFactoryError, match="aborted by user"):
                await _run_pipeline(
                    state, str(tmp_path),
                    mock_clarify, mock_implement, mock_evaluate,
                )

    @pytest.mark.asyncio
    async def test_cost_accumulates(self, tmp_path):
        """Cost from evaluation is added to state."""
        state = _make_state(tmp_path)
        state.cost_usd = 2.0  # Simulate implementation cost already accumulated

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(return_value="diff")
        mock_evaluate = AsyncMock(return_value=_make_report(cost=0.10))

        await _run_pipeline(
            state, str(tmp_path),
            mock_clarify, mock_implement, mock_evaluate,
        )

        # 2.0 (existing) + 0.10 (evaluation)
        assert state.cost_usd == pytest.approx(2.10)

    @pytest.mark.asyncio
    async def test_implementation_error_propagates(self, tmp_path):
        """Errors from implementation propagate up."""
        state = _make_state(tmp_path)

        mock_clarify = AsyncMock(return_value=_make_intent())
        mock_implement = AsyncMock(side_effect=DarkFactoryError("agent crashed"))
        mock_evaluate = AsyncMock()

        with pytest.raises(DarkFactoryError, match="agent crashed"):
            await _run_pipeline(
                state, str(tmp_path),
                mock_clarify, mock_implement, mock_evaluate,
            )

        mock_evaluate.assert_not_awaited()
