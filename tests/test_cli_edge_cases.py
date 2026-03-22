"""Edge-case tests for dark_factory.cli: input routing for all source types.

Covers Jira key variants, file paths with spaces/dots, inline descriptions
with special characters, flag combinations, and empty/malformed inputs.
"""

from __future__ import annotations

import pytest

from dark_factory.cli import ParsedArgs, parse_args, _classify_source, _slugify
from dark_factory.state import SourceInfo


# ---------------------------------------------------------------------------
# Jira key variants
# ---------------------------------------------------------------------------

class TestJiraKeyVariants:
    """Jira key regex: ^[A-Z][A-Z0-9]+-\\d+$"""

    def test_single_letter_project(self):
        # Only matches if first char is uppercase letter
        result = parse_args(["A-1"])
        # "A-1" does not match _JIRA_RE: needs [A-Z][A-Z0-9]+ (2+ uppercase chars)
        assert result.source.kind != "jira"

    def test_two_letter_project(self):
        result = parse_args(["AB-1"])
        assert result.source.kind == "jira"
        assert result.source.id == "ab-1"

    def test_long_project_prefix(self):
        result = parse_args(["LONGPROJECT-99999"])
        assert result.source.kind == "jira"
        assert result.source.id == "longproject-99999"

    def test_alphanumeric_project_prefix(self):
        result = parse_args(["PROJ2-42"])
        assert result.source.kind == "jira"
        assert result.source.id == "proj2-42"

    def test_leading_number_not_jira(self):
        # Must start with a letter per regex
        result = parse_args(["2PROJ-10"])
        assert result.source.kind != "jira"

    def test_lowercase_jira_not_matched(self):
        # Regex requires uppercase: ^[A-Z][A-Z0-9]+-\\d+$
        result = parse_args(["sdlc-123"])
        assert result.source.kind != "jira"

    def test_jira_key_zero_issue_number(self):
        result = parse_args(["PROJ-0"])
        assert result.source.kind == "jira"
        assert result.source.id == "proj-0"

    def test_jira_key_large_issue_number(self):
        result = parse_args(["PROJ-999999"])
        assert result.source.kind == "jira"

    def test_jira_key_with_trailing_space(self):
        # parse_args joins positional, _classify_source strips
        result = parse_args(["PROJ-1 "])
        # Trailing space is stripped in _classify_source
        assert result.source.kind == "jira"

    def test_jira_key_with_quotes(self):
        # Quoted values get stripped by _classify_source
        source = _classify_source('"PROJ-10"')
        assert source.kind == "jira"
        assert source.id == "proj-10"

    def test_jira_key_single_quotes(self):
        source = _classify_source("'PROJ-10'")
        assert source.kind == "jira"
        assert source.id == "proj-10"


# ---------------------------------------------------------------------------
# File path edge cases
# ---------------------------------------------------------------------------

class TestFilePathEdgeCases:
    def test_file_with_spaces_in_path(self):
        result = parse_args(["specs/my", "feature.md"])
        # parse_args joins positional: "specs/my feature.md"
        # Contains "/" so classified as file
        assert result.source.kind == "file"

    def test_file_with_dots_in_name(self):
        result = parse_args(["specs/v2.1.feature.md"])
        assert result.source.kind == "file"
        # stem is "v2.1.feature" since .md is the suffix
        assert result.source.id == "v2.1.feature"

    def test_yaml_extension(self):
        result = parse_args(["config.yaml"])
        assert result.source.kind == "file"
        assert result.source.id == "config"

    def test_yml_extension(self):
        result = parse_args(["spec.yml"])
        assert result.source.kind == "file"
        assert result.source.id == "spec"

    def test_txt_extension(self):
        result = parse_args(["notes.txt"])
        assert result.source.kind == "file"
        assert result.source.id == "notes"

    def test_deep_nested_path(self):
        result = parse_args(["a/b/c/d/spec.md"])
        assert result.source.kind == "file"
        assert result.source.id == "spec"

    def test_path_with_only_slash(self):
        result = parse_args(["src/component"])
        # Contains "/" -> file heuristic
        assert result.source.kind == "file"
        # No extension, stem is "component"
        assert result.source.id == "component"

    def test_dotfile_no_recognized_extension(self):
        # ".env" has suffix ".env" which is not in the recognized set
        # and has no "/" -> treated as inline
        result = parse_args([".env"])
        assert result.source.kind == "inline"

    def test_file_with_uppercase_extension(self):
        # ".MD" suffix won't match ".md" exactly
        result = parse_args(["SPEC.MD"])
        # Path(".MD").suffix is ".MD", not in recognized set, no "/"
        # Will be inline
        assert result.source.kind == "inline"

    def test_relative_dot_slash_path(self):
        result = parse_args(["./specs/feature.md"])
        assert result.source.kind == "file"
        assert result.source.id == "feature"


# ---------------------------------------------------------------------------
# Inline description edge cases
# ---------------------------------------------------------------------------

class TestInlineEdgeCases:
    def test_special_chars_in_description(self):
        result = parse_args(["add", "OAuth2.0", "&", "SSO", "support"])
        assert result.source.kind == "inline"
        assert result.source.raw == "add OAuth2.0 & SSO support"

    def test_inline_with_unicode(self):
        result = parse_args(["add", "emoji", "🎉", "support"])
        assert result.source.kind == "inline"
        assert "emoji" in result.source.raw

    def test_inline_slug_removes_special_chars(self):
        slug = _slugify("add OAuth2.0 & SSO support!")
        assert slug == "add-oauth2-0-sso-support"

    def test_inline_slug_strips_leading_trailing_hyphens(self):
        slug = _slugify("---hello world---")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_inline_slug_empty_input(self):
        slug = _slugify("")
        assert slug == "inline"

    def test_inline_slug_only_special_chars(self):
        slug = _slugify("!@#$%^&*()")
        assert slug == "inline"

    def test_inline_single_word(self):
        result = parse_args(["refactor"])
        assert result.source.kind == "inline"
        assert result.source.id == "refactor"

    def test_inline_with_numbers(self):
        result = parse_args(["fix", "bug", "42"])
        assert result.source.kind == "inline"
        assert result.source.raw == "fix bug 42"

    def test_inline_with_hyphens(self):
        result = parse_args(["add", "dark-mode", "toggle"])
        assert result.source.kind == "inline"
        assert "dark-mode" in result.source.raw

    def test_inline_slug_truncation_at_60(self):
        words = ["word"] * 30
        result = parse_args(words)
        assert len(result.source.id) <= 60

    def test_inline_with_backticks(self):
        result = parse_args(["update", "`config.yaml`", "parser"])
        assert result.source.kind == "inline"
        assert "`config.yaml`" in result.source.raw


# ---------------------------------------------------------------------------
# Flag combinations
# ---------------------------------------------------------------------------

class TestFlagCombinations:
    def test_dry_run_only(self):
        result = parse_args(["PROJ-1", "--dry-run"])
        assert result.dry_run is True
        assert result.resume is False

    def test_resume_only(self):
        result = parse_args(["PROJ-1", "--resume"])
        assert result.dry_run is False
        assert result.resume is True

    def test_both_flags(self):
        result = parse_args(["PROJ-1", "--dry-run", "--resume"])
        assert result.dry_run is True
        assert result.resume is True

    def test_flags_before_positional(self):
        result = parse_args(["--dry-run", "PROJ-1"])
        assert result.dry_run is True
        assert result.source.kind == "jira"
        assert result.source.id == "proj-1"

    def test_flags_between_positional(self):
        result = parse_args(["add", "--dry-run", "feature"])
        assert result.dry_run is True
        # Positional words joined: "add feature"
        assert result.source.raw == "add feature"

    def test_unknown_flags_ignored(self):
        result = parse_args(["PROJ-1", "--verbose", "--dry-run"])
        assert result.dry_run is True
        # --verbose is in flags but not checked, source still correct
        assert result.source.kind == "jira"

    def test_no_arguments(self):
        result = parse_args([])
        assert result.source.raw == ""
        assert result.source.kind == "inline"
        assert result.dry_run is False
        assert result.resume is False

    def test_only_flags_no_positional(self):
        result = parse_args(["--dry-run", "--resume"])
        assert result.dry_run is True
        assert result.resume is True
        assert result.source.raw == ""

    def test_flags_not_included_in_source_raw(self):
        result = parse_args(["add", "feature", "--dry-run"])
        assert "--dry-run" not in result.source.raw
        assert result.source.raw == "add feature"

    def test_file_with_both_flags(self):
        result = parse_args(["spec.md", "--dry-run", "--resume"])
        assert result.source.kind == "file"
        assert result.dry_run is True
        assert result.resume is True
