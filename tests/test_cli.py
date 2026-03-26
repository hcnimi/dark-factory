"""Tests for dark_factory.cli: argument parsing and input routing."""

from __future__ import annotations

from dark_factory.cli import ParsedArgs, parse_args


class TestParseArgsJira:
    def test_jira_key(self):
        result = parse_args(["SDLC-123"])
        assert result.source.kind == "jira"
        assert result.source.raw == "SDLC-123"
        assert result.source.id == "sdlc-123"

    def test_jira_key_with_resume(self):
        result = parse_args(["SDLC-123", "--resume"])
        assert result.source.kind == "jira"
        assert result.resume is True

    def test_jira_key_with_dry_run(self):
        result = parse_args(["SDLC-123", "--dry-run"])
        assert result.dry_run is True
        assert result.resume is False

    def test_different_project_prefix(self):
        result = parse_args(["DPPT-42"])
        assert result.source.kind == "jira"
        assert result.source.id == "dppt-42"


class TestParseArgsFile:
    def test_file_path_with_slash(self):
        result = parse_args(["specs/feature.md"])
        assert result.source.kind == "file"
        assert result.source.id == "feature"

    def test_file_path_markdown(self):
        result = parse_args(["my-feature.md"])
        assert result.source.kind == "file"
        assert result.source.id == "my-feature"

    def test_file_path_yaml(self):
        result = parse_args(["config.yaml"])
        assert result.source.kind == "file"
        assert result.source.id == "config"


class TestParseArgsInline:
    def test_inline_description(self):
        result = parse_args(["add", "dark", "mode", "toggle"])
        assert result.source.kind == "inline"
        assert result.source.raw == "add dark mode toggle"

    def test_inline_creates_slug_id(self):
        result = parse_args(["add", "dark", "mode"])
        assert result.source.id == "add-dark-mode"

    def test_inline_slug_truncated(self):
        long_desc = ["word"] * 30
        result = parse_args(long_desc)
        assert len(result.source.id) <= 60


class TestParseArgsFlags:
    def test_flags_not_in_source(self):
        result = parse_args(["SDLC-1", "--dry-run", "--resume"])
        assert result.source.raw == "SDLC-1"
        assert result.dry_run is True
        assert result.resume is True

    def test_no_flags(self):
        result = parse_args(["SDLC-1"])
        assert result.dry_run is False
        assert result.resume is False


class TestFromSpec:
    def test_from_spec_flag(self):
        result = parse_args(["--from-spec", "openspec/changes/dark-factory-dppt-88"])
        assert result.from_spec == "openspec/changes/dark-factory-dppt-88"
        assert result.source.kind == "spec"
        assert result.source.id == "dark-factory-dppt-88"

    def test_from_spec_equals_form(self):
        result = parse_args(["--from-spec=path/to/spec"])
        assert result.from_spec == "path/to/spec"
        assert result.source.kind == "spec"

    def test_from_spec_with_dry_run(self):
        result = parse_args(["--from-spec", "spec/dir", "--dry-run"])
        assert result.from_spec == "spec/dir"
        assert result.dry_run is True

    def test_from_spec_not_set_by_default(self):
        result = parse_args(["SDLC-123"])
        assert result.from_spec == ""


class TestToolAvailability:
    def test_git_available(self):
        # git should be available in the test environment
        result = parse_args(["TEST-1"])
        assert "git" not in result.missing_tools
