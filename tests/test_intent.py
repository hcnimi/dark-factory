"""Tests for dark_factory.intent."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from dark_factory.intent import (
    build_intent_prompt,
    build_extraction_prompt,
    clarify_intent,
    extract_intent_from_spec,
    is_structured_spec,
    parse_intent_response,
    INTENT_SYSTEM_PROMPT,
    EXTRACT_INTENT_SYSTEM_PROMPT,
)
from dark_factory.types import IntentDocument, SourceInfo, SourceKind


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

    def test_directory_source(self, tmp_path):
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "overview.md").write_text("# Multi-File Spec\nDetails here")
        source = SourceInfo(SourceKind.DIRECTORY, str(spec_dir), "specs")
        prompt = build_intent_prompt(source)
        assert "Multi-File Spec" in prompt
        assert "spec files" in prompt

    def test_directory_source_with_interview_context(self, tmp_path):
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "overview.md").write_text("# Feature")
        source = SourceInfo(SourceKind.DIRECTORY, str(spec_dir), "specs")
        prompt = build_intent_prompt(source, interview_context="Q1: Scope?\nA1: Everything")
        assert "Additional Context" in prompt
        assert "Scope?" in prompt

    def test_interview_context_none_unchanged(self):
        source = SourceInfo(SourceKind.INLINE, "add dark mode", "add-dark-mode")
        prompt_without = build_intent_prompt(source)
        prompt_with_none = build_intent_prompt(source, interview_context=None)
        assert prompt_without == prompt_with_none
        assert "Additional Context" not in prompt_without

    def test_interview_context_appended(self):
        source = SourceInfo(SourceKind.INLINE, "add dark mode", "add-dark-mode")
        context = "Q1: What scope?\nA1: All pages"
        prompt = build_intent_prompt(source, interview_context=context)
        assert "Additional Context from Clarification" in prompt
        assert "What scope?" in prompt
        assert "All pages" in prompt


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


class TestIsStructuredSpec:
    def test_gherkin_markers(self):
        content = "### Requirement: Foo\n#### Scenario: Bar\n- **GIVEN** something"
        assert is_structured_spec(content) is True

    def test_prose_returns_false(self):
        content = "Please add a dark mode toggle to the settings page."
        assert is_structured_spec(content) is False

    def test_single_marker_returns_false(self):
        content = "### Requirement: Only one marker here, nothing else structured."
        assert is_structured_spec(content) is False

    def test_real_spec_format(self):
        content = (
            "## ADDED Requirements\n\n"
            "### Requirement: Foo\n"
            "#### Scenario: Happy path\n"
            "- **GIVEN** a valid input\n"
            "- **WHEN** the user submits\n"
            "- **THEN** the system responds 200\n"
        )
        assert is_structured_spec(content) is True

    def test_changed_requirements_marker(self):
        content = (
            "## CHANGED Requirements\n\n"
            "### Requirement: Updated auth flow\n"
        )
        assert is_structured_spec(content) is True


class TestBuildExtractionPrompt:
    def test_includes_content(self):
        content = "### Requirement: Auth\n#### Scenario: Login"
        prompt = build_extraction_prompt(content)
        assert "Auth" in prompt
        assert "Login" in prompt
        assert "Extract" in prompt

    def test_without_interview_context(self):
        prompt = build_extraction_prompt("spec content")
        assert "Amendments" not in prompt

    def test_with_interview_context(self):
        prompt = build_extraction_prompt(
            "spec content",
            interview_context="Q: Batch support?\nA: Yes, up to 1000"
        )
        assert "Amendments from Clarification" in prompt
        assert "Batch support" in prompt
        assert "take priority" in prompt

    def test_extraction_system_prompt_preserves_detail(self):
        assert "Do NOT summarize or condense" in EXTRACT_INTENT_SYSTEM_PROMPT
        assert "50+" in EXTRACT_INTENT_SYSTEM_PROMPT


def _make_intent(**kwargs):
    defaults = {
        "title": "Auth Feature",
        "summary": "Add authentication",
        "acceptance_criteria": ["AC1", "AC2"],
    }
    defaults.update(kwargs)
    return IntentDocument(**defaults)


def _structured_content():
    return (
        "## ADDED Requirements\n\n"
        "### Requirement: Login\n"
        "#### Scenario: Valid credentials\n"
        "- **GIVEN** a registered user\n"
        "- **WHEN** they submit valid credentials\n"
        "- **THEN** they receive a 200 response\n"
    )


class TestClarifyIntentRouting:
    @pytest.mark.asyncio
    async def test_structured_spec_routes_to_extraction(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_structured_content())
        source = SourceInfo(SourceKind.FILE, str(spec), "spec")

        intent = _make_intent()
        with patch(
            "dark_factory.intent.extract_intent_from_spec",
            new_callable=AsyncMock,
            return_value=(intent, 0.02),
        ) as mock_extract:
            result, cost = await clarify_intent(source)
            mock_extract.assert_awaited_once()
            assert result.title == "Auth Feature"
            assert cost == 0.02

    @pytest.mark.asyncio
    async def test_directory_routes_to_extraction(self, tmp_path):
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text(_structured_content())
        source = SourceInfo(SourceKind.DIRECTORY, str(spec_dir), "specs")

        intent = _make_intent()
        with patch(
            "dark_factory.intent.extract_intent_from_spec",
            new_callable=AsyncMock,
            return_value=(intent, 0.02),
        ) as mock_extract:
            result, cost = await clarify_intent(source)
            mock_extract.assert_awaited_once()
            assert result.title == "Auth Feature"

    @pytest.mark.asyncio
    async def test_prose_routes_to_condensation(self):
        source = SourceInfo(SourceKind.INLINE, "add dark mode toggle", "dark-mode")

        intent = _make_intent(title="Dark Mode")
        with patch(
            "dark_factory.intent._clarify_intent_condensation",
            new_callable=AsyncMock,
            return_value=(intent, 0.01),
        ) as mock_condense:
            result, cost = await clarify_intent(source)
            mock_condense.assert_awaited_once()
            assert result.title == "Dark Mode"
            assert cost == 0.01


class TestExtractIntentFallback:
    @pytest.mark.asyncio
    async def test_extraction_failure_falls_back(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_structured_content())
        source = SourceInfo(SourceKind.FILE, str(spec), "spec")

        intent = _make_intent()
        with patch("claude_code_sdk.query", side_effect=RuntimeError("SDK error")), \
             patch(
                 "dark_factory.intent._clarify_intent_condensation",
                 new_callable=AsyncMock,
                 return_value=(intent, 0.03),
             ) as mock_condense:
            result, cost = await extract_intent_from_spec(source)
            mock_condense.assert_awaited_once()
            assert result.title == "Auth Feature"
            assert cost == 0.03
