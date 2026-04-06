"""Tests for dark_factory.types."""

import json
import pytest
from pathlib import Path

from dataclasses import dataclass

from dark_factory.types import (
    SourceKind,
    SourceInfo,
    classify_source,
    RunStatus,
    Gate,
    CriterionStatus,
    IntentDocument,
    DimensionScore,
    CriterionAssessment,
    EvaluationReport,
    SecurityPolicy,
    RunConfig,
    RunState,
    DarkFactoryError,
    extract_sdk_result,
)


class TestSourceClassification:
    @pytest.mark.parametrize("raw,expected_kind", [
        ("DPPT-1234", SourceKind.JIRA),
        ("ABC-1", SourceKind.JIRA),
        ("ZZ99-999", SourceKind.JIRA),
        ("add a login endpoint", SourceKind.INLINE),
        ("fix the broken tests", SourceKind.INLINE),
        ("/nonexistent/file.md", SourceKind.INLINE),
    ])
    def test_classify_source(self, raw, expected_kind):
        result = classify_source(raw)
        assert result.kind == expected_kind
        assert result.raw == raw.strip()

    def test_classify_file(self, tmp_path):
        f = tmp_path / "spec.md"
        f.write_text("# Spec")
        result = classify_source(str(f))
        assert result.kind == SourceKind.FILE
        assert result.id == "spec"

    def test_classify_inline_slug(self):
        result = classify_source("add user preferences endpoint")
        assert result.kind == SourceKind.INLINE
        assert result.id == "add-user-preferences-endpoint"

    def test_source_info_roundtrip(self):
        si = SourceInfo(kind=SourceKind.JIRA, raw="DPPT-123", id="DPPT-123")
        d = si.to_dict()
        restored = SourceInfo.from_dict(d)
        assert restored == si


class TestIntentDocument:
    def test_roundtrip(self):
        doc = IntentDocument(
            title="Add login",
            summary="Add login endpoint with JWT",
            acceptance_criteria=["Endpoint returns 200", "JWT token in response"],
        )
        d = doc.to_dict()
        restored = IntentDocument.from_dict(d)
        assert restored.title == doc.title
        assert restored.acceptance_criteria == doc.acceptance_criteria

    def test_format_for_display(self):
        doc = IntentDocument(
            title="My Feature",
            summary="A great feature",
            acceptance_criteria=["AC 1", "AC 2"],
        )
        text = doc.format_for_display()
        assert "# My Feature" in text
        assert "AC 1" in text
        assert "AC 2" in text


class TestEvaluationReport:
    def _make_report(self, scores_vals=None):
        scores = [
            DimensionScore("Intent Fidelity", scores_vals[0] if scores_vals else 9, "good"),
            DimensionScore("Correctness", scores_vals[1] if scores_vals else 8, "solid"),
            DimensionScore("Integration", scores_vals[2] if scores_vals else 9, "clean"),
        ]
        criteria = [
            CriterionAssessment("AC1", CriterionStatus.MET, "found in diff"),
        ]
        return EvaluationReport(scores=scores, criteria=criteria, model_used="sonnet", cost_usd=0.01)

    def test_roundtrip(self):
        report = self._make_report()
        d = report.to_dict()
        restored = EvaluationReport.from_dict(d)
        assert len(restored.scores) == 3
        assert restored.model_used == "sonnet"

    def test_is_passing(self):
        assert self._make_report([9, 8, 9]).is_passing()
        assert not self._make_report([9, 7, 9]).is_passing()

    def test_is_borderline(self):
        assert self._make_report([9, 6, 9]).is_borderline()
        assert not self._make_report([9, 8, 9]).is_borderline()
        assert not self._make_report([9, 4, 9]).is_borderline()

    def test_format_for_display(self):
        report = self._make_report()
        text = report.format_for_display()
        assert "Evaluation Report" in text
        assert "Intent Fidelity" in text


class TestRunConfig:
    def test_defaults(self):
        rc = RunConfig()
        assert rc.max_cost_usd == 10.0
        assert rc.gates == []
        assert not rc.dry_run

    def test_roundtrip(self):
        rc = RunConfig(gates=[Gate.INTENT, Gate.EVAL], dry_run=True)
        d = rc.to_dict()
        restored = RunConfig.from_dict(d)
        assert restored.gates == [Gate.INTENT, Gate.EVAL]
        assert restored.dry_run


class TestRunState:
    def _make_state(self, gates=None):
        source = SourceInfo(SourceKind.INLINE, "add feature", "add-feature")
        config = RunConfig(gates=gates or [])
        return RunState.create(source=source, config=config)

    def test_create_generates_id(self):
        state = self._make_state()
        assert len(state.run_id) == 12
        assert state.status == RunStatus.PENDING

    def test_save_and_load(self, tmp_path):
        state = self._make_state()
        state.save(str(tmp_path))
        path = state.state_path(str(tmp_path))
        assert path.exists()

        loaded = RunState.load(path)
        assert loaded.run_id == state.run_id
        assert loaded.source == state.source
        assert loaded.status == RunStatus.PENDING

    def test_roundtrip_with_intent(self, tmp_path):
        state = self._make_state()
        state.intent = IntentDocument("T", "S", ["AC1"])
        state.status = RunStatus.INTENT_COMPLETE
        state.save(str(tmp_path))

        loaded = RunState.load(state.state_path(str(tmp_path)))
        assert loaded.intent is not None
        assert loaded.intent.title == "T"
        assert loaded.status == RunStatus.INTENT_COMPLETE

    def test_gated_intent_roundtrip(self, tmp_path):
        state = self._make_state(gates=[Gate.INTENT])
        state.intent = IntentDocument("T", "S", ["AC1"])
        state.status = RunStatus.GATED_INTENT
        state.save(str(tmp_path))

        loaded = RunState.load(state.state_path(str(tmp_path)))
        assert loaded.status == RunStatus.GATED_INTENT
        assert loaded.config.gates == [Gate.INTENT]
        assert loaded.intent.title == "T"

    def test_gated_eval_roundtrip(self, tmp_path):
        state = self._make_state(gates=[Gate.EVAL])
        state.status = RunStatus.GATED_EVAL
        state.save(str(tmp_path))

        loaded = RunState.load(state.state_path(str(tmp_path)))
        assert loaded.status == RunStatus.GATED_EVAL

    def test_diff_path(self, tmp_path):
        state = self._make_state()
        path = state.diff_path(str(tmp_path))
        assert path.name == f"{state.run_id}.diff"
        assert path.parent.name == ".dark-factory"

    def test_state_dir_created(self, tmp_path):
        state = self._make_state()
        state_dir = state.state_dir(str(tmp_path))
        assert state_dir.exists()
        assert state_dir.name == ".dark-factory"


class TestExtractSdkResult:
    def test_extracts_from_result_message(self):
        """ResultMessage.result and .total_cost_usd are the primary source."""
        @dataclass
        class FakeResultMessage:
            result: str = "the output"
            total_cost_usd: float = 1.23

        messages = [FakeResultMessage()]
        text, cost = extract_sdk_result(messages)
        assert text == "the output"
        assert cost == 1.23

    def test_fallback_to_assistant_content_blocks(self):
        """When no ResultMessage, extract text from AssistantMessage content blocks."""
        @dataclass
        class FakeTextBlock:
            text: str = "block text"

        @dataclass
        class FakeAssistantMessage:
            content: list = None
            def __post_init__(self):
                self.content = [FakeTextBlock()]

        messages = [FakeAssistantMessage()]
        text, cost = extract_sdk_result(messages)
        assert text == "block text"
        assert cost == 0.0

    def test_empty_messages(self):
        text, cost = extract_sdk_result([])
        assert text == ""
        assert cost == 0.0

    def test_result_message_with_none_cost(self):
        @dataclass
        class FakeResultMessage:
            result: str = "output"
            total_cost_usd: float | None = None

        messages = [FakeResultMessage()]
        text, cost = extract_sdk_result(messages)
        assert text == "output"
        assert cost == 0.0

    def test_result_message_preferred_over_assistant(self):
        """ResultMessage.result takes priority over content blocks."""
        @dataclass
        class FakeTextBlock:
            text: str = "assistant text"

        @dataclass
        class FakeAssistantMessage:
            content: list = None
            def __post_init__(self):
                self.content = [FakeTextBlock()]

        @dataclass
        class FakeResultMessage:
            result: str = "final result"
            total_cost_usd: float = 0.5

        messages = [FakeAssistantMessage(), FakeResultMessage()]
        text, cost = extract_sdk_result(messages)
        assert text == "final result"
        assert cost == 0.5
