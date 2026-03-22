"""Tests for run_holdout_tests() and HoldoutResult from dark_factory.verify."""

from __future__ import annotations

import pytest

from dark_factory.verify import HoldoutResult, run_holdout_tests


class TestHoldoutResultDefaults:
    def test_defaults_passed_true(self):
        result = HoldoutResult()
        assert result.passed is True

    def test_defaults_failures_empty(self):
        result = HoldoutResult()
        assert result.failures == []

    def test_defaults_severity_warning(self):
        result = HoldoutResult()
        assert result.severity == "WARNING"

    def test_separate_instances_have_independent_failures(self):
        """Verify field(default_factory=list) prevents shared mutable default."""
        r1 = HoldoutResult()
        r2 = HoldoutResult()
        r1.failures.append("oops")
        assert r2.failures == []


class TestRunHoldoutTests:
    def test_empty_holdout_paths(self, tmp_path):
        result = run_holdout_tests(str(tmp_path), [])
        assert result.passed is True
        assert result.failures == []

    def test_all_tests_pass(self, tmp_path):
        passing = tmp_path / "test_pass.py"
        passing.write_text("def test_ok():\n    assert True\n")

        result = run_holdout_tests(str(tmp_path), [str(passing)])
        assert result.passed is True
        assert result.failures == []

    def test_a_test_fails(self, tmp_path):
        failing = tmp_path / "test_fail.py"
        failing.write_text("def test_bad():\n    assert False\n")

        result = run_holdout_tests(str(tmp_path), [str(failing)])
        assert result.passed is False
        assert len(result.failures) == 1
        assert str(failing) in result.failures[0]

    def test_mixed_results(self, tmp_path):
        passing = tmp_path / "test_pass.py"
        passing.write_text("def test_ok():\n    assert True\n")

        failing = tmp_path / "test_fail.py"
        failing.write_text("def test_bad():\n    assert False\n")

        result = run_holdout_tests(str(tmp_path), [str(passing), str(failing)])
        assert result.passed is False
        assert len(result.failures) == 1
        assert str(failing) in result.failures[0]
        # The passing test should not appear in failures
        assert not any(str(passing) in f for f in result.failures)

    def test_missing_test_file(self, tmp_path):
        nonexistent = str(tmp_path / "test_does_not_exist.py")

        result = run_holdout_tests(str(tmp_path), [nonexistent])
        assert result.passed is False
        assert len(result.failures) == 1
        assert "not found" in result.failures[0]

    def test_multiple_missing_files(self, tmp_path):
        paths = [
            str(tmp_path / "missing_a.py"),
            str(tmp_path / "missing_b.py"),
        ]

        result = run_holdout_tests(str(tmp_path), paths)
        assert result.passed is False
        assert len(result.failures) == 2
        assert all("not found" in f for f in result.failures)

    def test_severity_preserved(self, tmp_path):
        """run_holdout_tests returns a HoldoutResult with default severity."""
        result = run_holdout_tests(str(tmp_path), [])
        assert result.severity == "WARNING"
