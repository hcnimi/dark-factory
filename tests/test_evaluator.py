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

    def test_truncates_large_diff(self):
        intent = _make_intent()
        large_diff = "x" * 60_000
        prompt = build_evaluation_prompt(intent, large_diff)
        assert "truncated" in prompt
        assert len(prompt) < 55_000  # Truncated to ~50k + overhead

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

    def test_source_context_truncation(self):
        intent = _make_intent()
        large_context = "y" * 40_000
        prompt = build_evaluation_prompt(intent, "diff", source_context=large_context)
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
        with pytest.raises(json.JSONDecodeError):
            parse_evaluation_response("not json")

    def test_missing_scores_raises(self):
        response = json.dumps({"criteria": []})
        with pytest.raises(KeyError):
            parse_evaluation_response(response)
