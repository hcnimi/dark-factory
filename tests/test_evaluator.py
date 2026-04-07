"""Tests for dark_factory.evaluator."""

import json
import pytest

from dark_factory.evaluator import (
    build_evaluation_prompt,
    parse_evaluation_response,
    EVALUATOR_SYSTEM_PROMPT,
)
from dark_factory.types import (
    CriterionStatus,
    DarkFactoryError,
    IntentDocument,
)


def _make_intent():
    return IntentDocument(
        title="Add Login",
        summary="Add JWT login endpoint",
        acceptance_criteria=["Returns 200 on valid credentials", "Returns 401 on invalid"],
    )


class TestBuildEvaluationPrompt:
    def test_includes_intent(self):
        intent = _make_intent()
        prompt = build_evaluation_prompt(intent, "diff content")
        assert "Add Login" in prompt
        assert "Returns 200" in prompt
        assert "diff content" in prompt

    def test_does_not_truncate_moderate_diff_with_opus(self):
        intent = _make_intent()
        large_diff = "x" * 200_000
        prompt = build_evaluation_prompt(intent, large_diff, model="claude-opus-4-6")
        assert "truncated" not in prompt

    def test_truncates_very_large_diff_with_opus(self):
        intent = _make_intent()
        huge_diff = "x" * 600_000
        prompt = build_evaluation_prompt(intent, huge_diff, model="claude-opus-4-6")
        assert "truncated" in prompt

    def test_truncation_with_default_limits(self):
        intent = _make_intent()
        large_diff = "x" * 60_000
        prompt = build_evaluation_prompt(intent, large_diff, model="unknown-model")
        assert "truncated" in prompt
        assert len(prompt) < 55_000

    def test_includes_source_context(self):
        intent = _make_intent()
        prompt = build_evaluation_prompt(
            intent, "diff", source_context="## Full Spec\nDetailed requirements here"
        )
        assert "Original Specification" in prompt
        assert "Full Spec" in prompt
        assert "Detailed requirements here" in prompt

    def test_no_source_context_backward_compatible(self):
        intent = _make_intent()
        prompt = build_evaluation_prompt(intent, "diff")
        assert "Original Specification" not in prompt

    def test_source_context_no_truncation_with_opus(self):
        intent = _make_intent()
        large_context = "y" * 100_000
        prompt = build_evaluation_prompt(intent, "diff", source_context=large_context, model="claude-opus-4-6")
        assert "source context truncated" not in prompt

    def test_source_context_truncation_with_default_limits(self):
        intent = _make_intent()
        large_context = "y" * 40_000
        prompt = build_evaluation_prompt(intent, "diff", source_context=large_context, model="unknown-model")
        assert "source context truncated" in prompt

    def test_source_context_between_intent_and_diff(self):
        intent = _make_intent()
        prompt = build_evaluation_prompt(
            intent, "the diff", source_context="the spec"
        )
        intent_pos = prompt.index("Intent")
        spec_pos = prompt.index("Original Specification")
        diff_pos = prompt.index("## Diff")
        assert intent_pos < spec_pos < diff_pos


class TestParseEvaluationResponse:
    def test_valid_response(self):
        response = json.dumps({
            "scores": [
                {"dimension": "Intent Fidelity", "score": 9, "justification": "All ACs met"},
                {"dimension": "Correctness", "score": 8, "justification": "No bugs"},
                {"dimension": "Integration", "score": 7, "justification": "Mostly follows conventions"},
            ],
            "criteria": [
                {"criterion": "Returns 200", "status": "met", "evidence": "line 42"},
                {"criterion": "Returns 401", "status": "partial", "evidence": "incomplete"},
            ],
        })
        scores, criteria = parse_evaluation_response(response)
        assert len(scores) == 3
        assert scores[0].score == 9
        assert len(criteria) == 2
        assert criteria[1].status == CriterionStatus.PARTIAL

    def test_response_with_code_fences(self):
        inner = json.dumps({
            "scores": [
                {"dimension": "Intent Fidelity", "score": 10, "justification": "perfect"},
            ],
            "criteria": [],
        })
        response = f"```json\n{inner}\n```"
        scores, criteria = parse_evaluation_response(response)
        assert scores[0].score == 10

    def test_invalid_json_raises(self):
        with pytest.raises(DarkFactoryError):
            parse_evaluation_response("not json")

    def test_missing_scores_raises(self):
        response = json.dumps({"criteria": []})
        with pytest.raises(DarkFactoryError, match="Invalid evaluation response"):
            parse_evaluation_response(response)

    def test_invalid_score_value_raises(self):
        response = json.dumps({
            "scores": [
                {"dimension": "Intent Fidelity", "score": "not-a-number", "justification": "x"},
            ],
            "criteria": [],
        })
        with pytest.raises(DarkFactoryError, match="Invalid evaluation response"):
            parse_evaluation_response(response)

    def test_invalid_criterion_status_raises(self):
        response = json.dumps({
            "scores": [
                {"dimension": "Intent Fidelity", "score": 9, "justification": "x"},
            ],
            "criteria": [
                {"criterion": "AC1", "status": "fulfilled", "evidence": "x"},
            ],
        })
        with pytest.raises(DarkFactoryError, match="Invalid evaluation response"):
            parse_evaluation_response(response)
