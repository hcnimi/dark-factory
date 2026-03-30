"""Tests for Phase 6.5: test generation agent and pipeline integration."""

from __future__ import annotations

import asyncio

import pytest

from dark_factory.agents import (
    MAX_TURNS_TEST_GEN,
    MODEL_SONNET,
    TOOLS_REVIEW,
    _sdk_query,
    call_test_gen,
)
from dark_factory.pipeline import (
    Phase6_5Result,
    _detect_test_dir,
    _extract_section,
    run_phase_6_5,
)
from dark_factory.state import PipelineState, SourceInfo


# ═══════════════════════════════════════════════════════════════════════════════
# Task 6.1: Unit tests for call_test_gen()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestGenConstants:
    """Verify model, turns, and tools configuration for the test-gen agent."""

    def test_max_turns_test_gen_is_3(self):
        assert MAX_TURNS_TEST_GEN == 3

    def test_uses_sonnet_model(self):
        assert MODEL_SONNET == "sonnet"

    def test_uses_read_only_tools(self):
        assert TOOLS_REVIEW == ["Read", "Glob", "Grep"]
        assert "Edit" not in TOOLS_REVIEW
        assert "Write" not in TOOLS_REVIEW
        assert "Bash" not in TOOLS_REVIEW


class TestCallTestGenDryRun:
    """Verify dry_run short-circuits with placeholder output and zero cost."""

    def test_dry_run_returns_skip_message(self):
        output, cost, num_turns = asyncio.run(
            call_test_gen("generate tests", worktree_path="/tmp", dry_run=True)
        )
        assert output == "[dry-run] test generation skipped"
        assert cost == 0.0
        assert num_turns == 0

    def test_dry_run_cost_is_zero(self):
        _, cost, _ = asyncio.run(
            call_test_gen("any prompt", worktree_path="/tmp", dry_run=True)
        )
        assert cost == 0.0


class TestSdkQueryRaisesOnMissingSDK:
    """Verify _sdk_query raises ImportError when SDK is unavailable."""

    def test_sdk_query_raises_import_error(self, monkeypatch):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "claude_code_sdk":
                raise ImportError("No module named 'claude_code_sdk'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="claude-code-sdk is required"):
            asyncio.run(
                _sdk_query("test", model="sonnet", max_turns=1, allowed_tools=[])
            )


class TestCallTestGenSdkUnavailable:
    """When the SDK is unavailable, _sdk_query returns a placeholder."""

    def test_output_contains_sdk_unavailable(self, monkeypatch):
        async def _fake_sdk_query(prompt, **kwargs):
            return [f"[sdk-unavailable] prompt: {prompt[:200]}"], 0.0, 0

        monkeypatch.setattr("dark_factory.agents._sdk_query", _fake_sdk_query)
        output, cost, num_turns = asyncio.run(
            call_test_gen("generate tests", worktree_path="/tmp", dry_run=False)
        )
        assert "sdk-unavailable" in output

    def test_cost_is_zero_without_sdk(self, monkeypatch):
        async def _fake_sdk_query(prompt, **kwargs):
            return [f"[sdk-unavailable] prompt: {prompt[:200]}"], 0.0, 0

        monkeypatch.setattr("dark_factory.agents._sdk_query", _fake_sdk_query)
        _, cost, _ = asyncio.run(
            call_test_gen("generate tests", worktree_path="/tmp", dry_run=False)
        )
        assert cost == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Task 6.2: Unit tests for Phase 6.5 pipeline helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractSection:
    """Verify _extract_section parses content between ### markers."""

    def test_extracts_content_between_markers(self):
        text = (
            "preamble\n"
            "### VISIBLE_TESTS_START\n"
            "def test_foo():\n"
            "    assert True\n"
            "### VISIBLE_TESTS_END\n"
            "epilogue\n"
        )
        result = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        assert result == "def test_foo():\n    assert True"

    def test_missing_start_marker_returns_empty(self):
        text = "no markers here\n### VISIBLE_TESTS_END\n"
        result = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        assert result == ""

    def test_missing_end_marker_returns_empty(self):
        text = "### VISIBLE_TESTS_START\nsome content\n"
        result = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        assert result == ""

    def test_empty_content_between_markers(self):
        text = "### VISIBLE_TESTS_START\n### VISIBLE_TESTS_END\n"
        result = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        assert result == ""

    def test_whitespace_around_markers(self):
        text = "###  VISIBLE_TESTS_START \ncode here\n### VISIBLE_TESTS_END\n"
        result = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        assert result == "code here"

    def test_holdout_section(self):
        text = (
            "### HOLDOUT_TESTS_START\n"
            "def test_edge():\n"
            "    pass\n"
            "### HOLDOUT_TESTS_END\n"
        )
        result = _extract_section(text, "HOLDOUT_TESTS_START", "HOLDOUT_TESTS_END")
        assert result == "def test_edge():\n    pass"

    def test_multiple_sections_extracts_first(self):
        text = (
            "### VISIBLE_TESTS_START\nfirst\n### VISIBLE_TESTS_END\n"
            "### HOLDOUT_TESTS_START\nsecond\n### HOLDOUT_TESTS_END\n"
        )
        visible = _extract_section(text, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
        holdout = _extract_section(text, "HOLDOUT_TESTS_START", "HOLDOUT_TESTS_END")
        assert visible == "first"
        assert holdout == "second"


class TestDetectTestDir:
    """Verify _detect_test_dir picks the right directory based on project markers."""

    def test_conftest_py_yields_tests(self, tmp_path):
        (tmp_path / "conftest.py").touch()
        assert _detect_test_dir(str(tmp_path)) == "tests"

    def test_tests_dir_yields_tests(self, tmp_path):
        (tmp_path / "tests").mkdir()
        assert _detect_test_dir(str(tmp_path)) == "tests"

    def test_test_dir_yields_test(self, tmp_path):
        (tmp_path / "test").mkdir()
        assert _detect_test_dir(str(tmp_path)) == "test"

    def test_dunder_tests_dir_yields_dunder_tests(self, tmp_path):
        (tmp_path / "__tests__").mkdir()
        assert _detect_test_dir(str(tmp_path)) == "__tests__"

    def test_spec_dir_yields_spec(self, tmp_path):
        (tmp_path / "spec").mkdir()
        assert _detect_test_dir(str(tmp_path)) == "spec"

    def test_pyproject_toml_yields_tests(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert _detect_test_dir(str(tmp_path)) == "tests"

    def test_setup_py_yields_tests(self, tmp_path):
        (tmp_path / "setup.py").touch()
        assert _detect_test_dir(str(tmp_path)) == "tests"

    def test_package_json_yields_dunder_tests(self, tmp_path):
        (tmp_path / "package.json").touch()
        assert _detect_test_dir(str(tmp_path)) == "__tests__"

    def test_empty_dir_defaults_to_tests(self, tmp_path):
        assert _detect_test_dir(str(tmp_path)) == "tests"


class TestPhase6_5Result:
    """Verify Phase6_5Result dataclass fields and defaults."""

    def test_default_fields(self):
        r = Phase6_5Result()
        assert r.visible_test_paths == []
        assert r.holdout_test_paths == []
        assert r.cost_usd == 0.0

    def test_custom_fields(self):
        r = Phase6_5Result(
            visible_test_paths=["/tmp/visible.py"],
            holdout_test_paths=["/tmp/holdout.py"],
            cost_usd=0.42,
        )
        assert r.visible_test_paths == ["/tmp/visible.py"]
        assert r.holdout_test_paths == ["/tmp/holdout.py"]
        assert r.cost_usd == 0.42

    def test_lists_are_independent(self):
        r1 = Phase6_5Result()
        r2 = Phase6_5Result()
        r1.visible_test_paths.append("a")
        assert r2.visible_test_paths == []


@pytest.fixture
def state(tmp_path):
    return PipelineState(
        source=SourceInfo(kind="jira", raw="TEST-1", id="test-1"),
        repo_root=str(tmp_path),
        branch="dark-factory/test-1",
    )


class TestRunPhase6_5EmptySpecs:
    """Empty spec_texts should short-circuit and return an empty result."""

    def test_empty_specs_returns_empty_result(self, state):
        result = asyncio.run(
            run_phase_6_5(state, "/tmp/wt", spec_texts=[], dry_run=False)
        )
        assert isinstance(result, Phase6_5Result)
        assert result.visible_test_paths == []
        assert result.holdout_test_paths == []
        assert result.cost_usd == 0.0

    def test_empty_specs_does_not_modify_state(self, state):
        asyncio.run(
            run_phase_6_5(state, "/tmp/wt", spec_texts=[])
        )
        assert state.visible_test_paths == []
        assert state.holdout_test_paths == []


class TestRunPhase6_5DryRun:
    """dry_run=True should short-circuit and return an empty result."""

    def test_dry_run_returns_empty_result(self, state):
        result = asyncio.run(
            run_phase_6_5(
                state, "/tmp/wt",
                spec_texts=["Given a user exists"],
                dry_run=True,
            )
        )
        assert isinstance(result, Phase6_5Result)
        assert result.visible_test_paths == []
        assert result.holdout_test_paths == []
        assert result.cost_usd == 0.0

    def test_dry_run_does_not_modify_state(self, state):
        asyncio.run(
            run_phase_6_5(
                state, "/tmp/wt",
                spec_texts=["Given a user exists"],
                dry_run=True,
            )
        )
        assert state.visible_test_paths == []
        assert state.holdout_test_paths == []
