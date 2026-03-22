"""Tests for dark_factory.ingest: Jira, file, and inline ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dark_factory.ingest import (
    TicketFields,
    _extract_ac_from_description,
    _extract_sections,
    _parse_interview_response,
    _parse_yaml_frontmatter,
    extract_keywords,
    ingest_file,
    ingest_jira,
    search_codebase_for_keywords,
)


# ---------------------------------------------------------------------------
# TicketFields
# ---------------------------------------------------------------------------

class TestTicketFields:
    def test_to_dict(self):
        t = TicketFields(summary="Add login", labels=["auth"])
        d = t.to_dict()
        assert d["summary"] == "Add login"
        assert d["labels"] == ["auth"]

    def test_searchable_text(self):
        t = TicketFields(
            summary="Add dark mode",
            acceptance_criteria=["Toggle in settings", "Persists across sessions"],
        )
        text = t.searchable_text()
        assert "dark mode" in text
        assert "Toggle in settings" in text

    def test_defaults(self):
        t = TicketFields()
        assert t.summary == ""
        assert t.acceptance_criteria == []
        assert t.labels == []


# ---------------------------------------------------------------------------
# Jira ingestion
# ---------------------------------------------------------------------------

class TestExtractAcFromDescription:
    def test_extracts_bullet_points(self):
        desc = """
Some description text.

## Acceptance Criteria
- Users can toggle dark mode
- Setting persists across sessions
- Default follows system preference
"""
        ac = _extract_ac_from_description(desc)
        assert len(ac) == 3
        assert "Users can toggle dark mode" in ac

    def test_numbered_list(self):
        desc = """
## Acceptance Criteria
1. First criterion
2. Second criterion
"""
        ac = _extract_ac_from_description(desc)
        assert len(ac) == 2
        assert "First criterion" in ac

    def test_no_ac_section(self):
        desc = "Just a description with no acceptance criteria section."
        ac = _extract_ac_from_description(desc)
        assert ac == []

    def test_ac_heading_case_insensitive(self):
        desc = """
# acceptance criteria
- Item one
"""
        ac = _extract_ac_from_description(desc)
        assert len(ac) == 1

    def test_ac_abbreviation(self):
        desc = """
## AC
* Criterion A
* Criterion B
"""
        ac = _extract_ac_from_description(desc)
        assert len(ac) == 2


class TestIngestJira:
    @patch("dark_factory.ingest._fetch_jira_via_mcp")
    def test_extracts_fields(self, mock_fetch):
        mock_fetch.return_value = {
            "fields": {
                "summary": "Add dark mode toggle",
                "description": "## Acceptance Criteria\n- Toggle works",
                "labels": ["frontend", "ux"],
                "components": [{"name": "webapp"}, {"name": "settings"}],
            }
        }
        ticket = ingest_jira("SDLC-123")
        assert ticket.summary == "Add dark mode toggle"
        assert ticket.labels == ["frontend", "ux"]
        assert ticket.components == ["webapp", "settings"]
        assert "Toggle works" in ticket.acceptance_criteria

    @patch("dark_factory.ingest._fetch_jira_via_mcp")
    def test_empty_response(self, mock_fetch):
        mock_fetch.return_value = {}
        ticket = ingest_jira("SDLC-999")
        assert ticket.summary == ""
        assert ticket.acceptance_criteria == []

    @patch("dark_factory.ingest._fetch_jira_via_mcp")
    def test_custom_ac_field(self, mock_fetch):
        mock_fetch.return_value = {
            "fields": {
                "summary": "Feature X",
                "description": "Some desc",
                "customfield_10035": "AC line 1\nAC line 2\n",
                "labels": [],
                "components": [],
            }
        }
        ticket = ingest_jira("PROJ-1")
        assert len(ticket.acceptance_criteria) == 2
        assert "AC line 1" in ticket.acceptance_criteria

    @patch("dark_factory.ingest._fetch_jira_via_mcp")
    def test_components_as_strings(self, mock_fetch):
        """Handle components as plain strings rather than objects."""
        mock_fetch.return_value = {
            "fields": {
                "summary": "Test",
                "components": ["comp-a", "comp-b"],
                "labels": [],
            }
        }
        ticket = ingest_jira("TEST-1")
        assert ticket.components == ["comp-a", "comp-b"]

    @patch("dark_factory.ingest._fetch_jira_via_mcp")
    def test_none_fields_handled(self, mock_fetch):
        """None values in fields should not cause errors."""
        mock_fetch.return_value = {
            "fields": {
                "summary": "Test",
                "description": None,
                "labels": None,
                "components": None,
            }
        }
        ticket = ingest_jira("TEST-2")
        assert ticket.summary == "Test"
        assert ticket.labels == []
        assert ticket.components == []


# ---------------------------------------------------------------------------
# File ingestion
# ---------------------------------------------------------------------------

class TestParseYamlFrontmatter:
    def test_extracts_metadata(self):
        content = "---\ntitle: My Feature\nlabels: [frontend, ux]\n---\n\n# Body"
        meta, body = _parse_yaml_frontmatter(content)
        assert meta["title"] == "My Feature"
        assert meta["labels"] == ["frontend", "ux"]
        assert "# Body" in body

    def test_no_frontmatter(self):
        content = "# Just a heading\nSome text."
        meta, body = _parse_yaml_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_simple_key_value(self):
        content = "---\nsummary: Add login page\ncomponents: auth\n---\nBody."
        meta, body = _parse_yaml_frontmatter(content)
        assert meta["summary"] == "Add login page"
        assert meta["components"] == "auth"


class TestExtractSections:
    def test_multiple_sections(self):
        body = "# Summary\nThe summary.\n\n## Acceptance Criteria\n- AC1\n- AC2\n"
        sections = _extract_sections(body)
        assert "summary" in sections
        assert "acceptance criteria" in sections
        assert "AC1" in sections["acceptance criteria"]

    def test_empty_body(self):
        sections = _extract_sections("")
        assert sections == {}


class TestIngestFile:
    def test_with_frontmatter(self, tmp_path):
        spec = tmp_path / "feature.md"
        spec.write_text(
            "---\nsummary: Add dark mode\nlabels: [ui]\n---\n\n"
            "# Description\nToggle support.\n\n"
            "## Acceptance Criteria\n- Toggle works\n- Persists\n"
        )
        ticket = ingest_file(str(spec))
        assert ticket.summary == "Add dark mode"
        assert ticket.labels == ["ui"]
        assert len(ticket.acceptance_criteria) == 2

    def test_without_frontmatter(self, tmp_path):
        spec = tmp_path / "feature.md"
        spec.write_text(
            "# Add Search Feature\n\n"
            "## Description\nFull-text search.\n\n"
            "## Acceptance Criteria\n- Search bar visible\n- Results paginated\n\n"
            "## Constraints\n- Must use existing index\n"
        )
        ticket = ingest_file(str(spec))
        assert "Search" in ticket.summary
        assert len(ticket.acceptance_criteria) == 2
        assert len(ticket.constraints) == 1

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest_file(str(tmp_path / "nonexistent.md"))

    def test_frontmatter_labels_as_string(self, tmp_path):
        spec = tmp_path / "feature.md"
        spec.write_text("---\nlabels: backend\n---\n\n# Feature\n")
        ticket = ingest_file(str(spec))
        assert ticket.labels == ["backend"]

    def test_frontmatter_with_title_fallback(self, tmp_path):
        spec = tmp_path / "feature.md"
        spec.write_text("---\ntitle: Feature Title\n---\n\nBody text.\n")
        ticket = ingest_file(str(spec))
        assert ticket.summary == "Feature Title"

    def test_no_heading_uses_first_line(self, tmp_path):
        spec = tmp_path / "feature.md"
        spec.write_text("This is a plain text description.\nMore text.\n")
        ticket = ingest_file(str(spec))
        assert "plain text description" in ticket.summary


# ---------------------------------------------------------------------------
# Inline interview response parsing
# ---------------------------------------------------------------------------

class TestParseInterviewResponse:
    def test_parses_json_block(self):
        text = """Here's the structured ticket:

```json
{
  "summary": "Add dark mode toggle",
  "description": "Users need dark mode",
  "acceptance_criteria": ["Toggle works", "Persists"],
  "labels": ["frontend"],
  "components": ["ui"],
  "constraints": ["No new deps"]
}
```
"""
        ticket = _parse_interview_response(text)
        assert ticket.summary == "Add dark mode toggle"
        assert len(ticket.acceptance_criteria) == 2
        assert ticket.labels == ["frontend"]
        assert ticket.constraints == ["No new deps"]

    def test_invalid_json_falls_back(self):
        text = "Just some text without JSON."
        ticket = _parse_interview_response(text)
        assert ticket.summary == "Just some text without JSON."
        assert ticket.description == text

    def test_empty_response(self):
        ticket = _parse_interview_response("")
        assert ticket.summary == ""

    def test_partial_json_falls_back(self):
        text = "Here:\n```json\n{invalid json}\n```\n"
        ticket = _parse_interview_response(text)
        # Falls back to first line as summary
        assert ticket.description == text


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_extracts_identifiers(self):
        ticket = TicketFields(
            summary="Add DarkMode toggle to SettingsPanel",
            acceptance_criteria=["user_preferences table updated"],
        )
        kw = extract_keywords(ticket)
        assert "DarkMode" in kw
        assert "SettingsPanel" in kw
        assert "user_preferences" in kw

    def test_filters_stop_words(self):
        ticket = TicketFields(summary="Add a new feature to the system")
        kw = extract_keywords(ticket)
        # Common stop words should be filtered
        lower_kw = [k.lower() for k in kw]
        assert "the" not in lower_kw
        assert "add" not in lower_kw

    def test_extracts_backtick_identifiers(self):
        ticket = TicketFields(
            summary="Update `config.yaml` parser",
            acceptance_criteria=["Handle `nested.keys` properly"],
        )
        kw = extract_keywords(ticket)
        assert "config.yaml" in kw

    def test_caps_at_30(self):
        words = " ".join(f"UniqueWord{i}" for i in range(50))
        ticket = TicketFields(summary=words)
        kw = extract_keywords(ticket)
        assert len(kw) <= 30

    def test_empty_ticket(self):
        ticket = TicketFields()
        kw = extract_keywords(ticket)
        assert kw == []


class TestSearchCodebaseForKeywords:
    def test_finds_matching_files(self, tmp_path):
        # Create source files with keywords
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("class DarkMode:\n    pass\n")
        (src / "utils.py").write_text("def helper(): pass\n")

        results = search_codebase_for_keywords(["DarkMode"], str(src))
        assert len(results) == 1
        assert "app.py" in results[0]

    def test_respects_max_results(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(25):
            (src / f"file{i}.py").write_text("KEYWORD = True\n")

        results = search_codebase_for_keywords(["KEYWORD"], str(src), max_results=5)
        assert len(results) <= 5

    def test_empty_keywords(self, tmp_path):
        results = search_codebase_for_keywords([], str(tmp_path))
        assert results == []

    def test_nonexistent_dir(self):
        results = search_codebase_for_keywords(["test"], "/nonexistent/path")
        assert results == []

    def test_deduplicates_across_keywords(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "module.py").write_text("class DarkMode:\n    dark_mode = True\n")

        results = search_codebase_for_keywords(
            ["DarkMode", "dark_mode"], str(src),
        )
        # Same file found by both keywords, should appear only once
        assert len(results) == 1
