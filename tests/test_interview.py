"""Tests for dark_factory.interview."""

import json
import pytest

from dark_factory.interview import (
    build_interview_prompt,
    parse_interview_response,
    format_amplification_context,
)
from dark_factory.types import DarkFactoryError, InterviewQA, SourceInfo, SourceKind


class TestBuildInterviewPrompt:
    def test_inline_source(self):
        source = SourceInfo(SourceKind.INLINE, "add dark mode", "add-dark-mode")
        prompt = build_interview_prompt(source)
        assert "add dark mode" in prompt
        assert "ambiguities" in prompt

    def test_file_source(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text("# My Feature\nDetailed specification here")
        source = SourceInfo(SourceKind.FILE, str(spec), "spec")
        prompt = build_interview_prompt(source)
        assert "My Feature" in prompt
        assert "specification" in prompt.lower()

    def test_directory_source(self, tmp_path):
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "overview.md").write_text("# My Multi-File Feature\nDetails")
        source = SourceInfo(SourceKind.DIRECTORY, str(spec_dir), "specs")
        prompt = build_interview_prompt(source)
        assert "My Multi-File Feature" in prompt
        assert "multiple files" in prompt
        assert "ambiguities" in prompt

    def test_jira_source_raises(self):
        source = SourceInfo(SourceKind.JIRA, "DPPT-123", "DPPT-123")
        with pytest.raises(DarkFactoryError, match="JIRA integration is not yet implemented"):
            build_interview_prompt(source)


class TestParseInterviewResponse:
    def test_valid_json_with_questions(self):
        response = json.dumps({"questions": ["What scope?", "Which users?"]})
        questions = parse_interview_response(response)
        assert len(questions) == 2
        assert "What scope?" in questions

    def test_empty_questions_list(self):
        response = json.dumps({"questions": []})
        questions = parse_interview_response(response)
        assert questions == []

    def test_json_with_code_fences(self):
        response = '```json\n{"questions": ["Q1"]}\n```'
        questions = parse_interview_response(response)
        assert questions == ["Q1"]

    def test_invalid_json_raises(self):
        with pytest.raises(DarkFactoryError):
            parse_interview_response("not json at all")

    def test_missing_questions_key(self):
        response = json.dumps({"other": "data"})
        questions = parse_interview_response(response)
        assert questions == []


class TestFormatAmplificationContext:
    def test_readable_qa(self):
        qas = [
            InterviewQA(question="What scope?", answer="All pages"),
            InterviewQA(question="Which users?", answer="Admin only"),
        ]
        text = format_amplification_context(qas)
        assert "Q1: What scope?" in text
        assert "A1: All pages" in text
        assert "Q2: Which users?" in text
        assert "A2: Admin only" in text

    def test_truncation_at_5000_chars(self):
        qas = [
            InterviewQA(question=f"Q{i}?", answer="A" * 1000)
            for i in range(10)
        ]
        text = format_amplification_context(qas)
        assert len(text) <= 5020  # 5000 + "... (truncated)" + newline
        assert "truncated" in text
