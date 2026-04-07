"""Tests for dark_factory.spec_analyzer."""

import json
import pytest

from dark_factory.spec_analyzer import (
    build_spec_analysis_prompt,
    parse_spec_analysis_response,
)
from dark_factory.types import IntentDocument, SpecAnalysisReport, DimensionScore


class TestBuildSpecAnalysisPrompt:
    def test_includes_intent_fields(self):
        intent = IntentDocument("Add Login", "JWT auth endpoint", ["Returns 200", "Includes JWT"])
        prompt = build_spec_analysis_prompt(intent)
        assert "Add Login" in prompt
        assert "JWT auth endpoint" in prompt
        assert "Returns 200" in prompt
        assert "Includes JWT" in prompt


class TestParseSpecAnalysisResponse:
    def test_valid_json(self):
        response = json.dumps({
            "scores": [
                {"dimension": "Clarity", "score": 8, "justification": "Clear"},
                {"dimension": "Testability", "score": 7, "justification": "Testable"},
                {"dimension": "Completeness", "score": 6, "justification": "Missing edges"},
            ],
            "suggestions": ["Add error cases"],
        })
        scores, suggestions = parse_spec_analysis_response(response)
        assert len(scores) == 3
        assert scores[0].dimension == "Clarity"
        assert scores[0].score == 8
        assert suggestions == ["Add error cases"]

    def test_json_with_code_fences(self):
        response = '```json\n{"scores": [{"dimension": "Clarity", "score": 9, "justification": "OK"}], "suggestions": []}\n```'
        scores, suggestions = parse_spec_analysis_response(response)
        assert len(scores) == 1
        assert suggestions == []

    def test_missing_suggestions_key(self):
        response = json.dumps({
            "scores": [{"dimension": "Clarity", "score": 9, "justification": "OK"}],
        })
        scores, suggestions = parse_spec_analysis_response(response)
        assert len(scores) == 1
        assert suggestions == []


class TestSpecAnalysisReport:
    def _make_report(self, score_values):
        scores = [
            DimensionScore(dimension=f"Dim{i}", score=v, justification="test")
            for i, v in enumerate(score_values)
        ]
        return SpecAnalysisReport(
            scores=scores, suggestions=["Fix it"], model_used="test", cost_usd=0.01,
        )

    def test_has_warnings_below_7(self):
        report = self._make_report([8, 6, 9])
        assert report.has_warnings()

    def test_no_warnings_all_7_plus(self):
        report = self._make_report([8, 7, 9])
        assert not report.has_warnings()

    def test_format_for_display(self):
        report = self._make_report([8, 6, 9])
        text = report.format_for_display()
        assert "Spec Analysis" in text
        assert "(!)" in text  # warning marker for score 6
        assert "Fix it" in text

    def test_to_dict_roundtrip(self):
        report = self._make_report([8, 7, 9])
        d = report.to_dict()
        restored = SpecAnalysisReport.from_dict(d)
        assert len(restored.scores) == 3
        assert restored.suggestions == ["Fix it"]
        assert restored.model_used == "test"
