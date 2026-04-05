"""Tests for dark_factory.intent."""

import json
import pytest

from dark_factory.intent import (
    build_intent_prompt,
    parse_intent_response,
    INTENT_SYSTEM_PROMPT,
)
from dark_factory.types import SourceInfo, SourceKind


class TestBuildIntentPrompt:
    def test_inline_source(self):
        source = SourceInfo(SourceKind.INLINE, "add dark mode", "add-dark-mode")
        prompt = build_intent_prompt(source)
        assert "add dark mode" in prompt
        assert "feature request" in prompt

    def test_file_source(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text("# My Feature\nDetails here")
        source = SourceInfo(SourceKind.FILE, str(spec), "spec")
        prompt = build_intent_prompt(source)
        assert "My Feature" in prompt
        assert "spec file" in prompt

    def test_jira_source(self):
        source = SourceInfo(SourceKind.JIRA, "DPPT-123", "DPPT-123")
        prompt = build_intent_prompt(source)
        assert "DPPT-123" in prompt


class TestParseIntentResponse:
    def test_valid_json(self):
        response = json.dumps({
            "title": "Add Login",
            "summary": "Add JWT login endpoint",
            "acceptance_criteria": ["Returns 200", "Includes JWT"],
        })
        doc = parse_intent_response(response)
        assert doc.title == "Add Login"
        assert len(doc.acceptance_criteria) == 2

    def test_json_with_code_fences(self):
        response = '```json\n{"title": "T", "summary": "S", "acceptance_criteria": ["AC"]}\n```'
        doc = parse_intent_response(response)
        assert doc.title == "T"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_intent_response("not json at all")

    def test_missing_field_raises(self):
        response = json.dumps({"title": "T", "summary": "S"})
        with pytest.raises(KeyError):
            parse_intent_response(response)
