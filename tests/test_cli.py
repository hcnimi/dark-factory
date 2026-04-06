"""Tests for dark_factory.__main__ CLI."""

import json
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from dark_factory.__main__ import (
    build_parser,
    _preflight,
    _handle_gate,
    EXIT_GATED,
)
from dark_factory.types import (
    DarkFactoryError,
    Gate,
    RunConfig,
    RunState,
    RunStatus,
    SourceInfo,
    SourceKind,
    IntentDocument,
)


class TestBuildParser:
    def test_version(self, capsys):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--version"])
        assert exc.value.code == 0

    def test_run_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["run", "add dark mode"])
        assert args.command == "run"
        assert args.input == "add dark mode"
        assert args.max_cost == 10.0
        assert not args.dry_run

    def test_run_with_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "run", "DPPT-123",
            "--max-cost", "5.0",
            "--gate-intent",
            "--gate-eval",
            "--in-place",
            "--dry-run",
        ])
        assert args.max_cost == 5.0
        assert args.gate_intent
        assert args.gate_eval
        assert args.in_place
        assert args.dry_run

    def test_evaluate_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["evaluate", "feature/login"])
        assert args.command == "evaluate"
        assert args.branch == "feature/login"

    def test_evaluate_with_intent(self):
        parser = build_parser()
        args = parser.parse_args(["evaluate", "my-branch", "--intent", "intent.md"])
        assert args.intent == "intent.md"

    def test_init_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["init"])
        assert args.command == "init"

    def test_no_command(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


    def test_run_with_resume(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--resume", "abc123def456"])
        assert args.command == "run"
        assert args.resume == "abc123def456"
        assert args.input is None

    def test_run_input_optional_with_resume(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--resume", "abc123"])
        assert args.resume == "abc123"
        assert args.input is None

    def test_run_no_input_no_resume(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.input is None
        assert args.resume is None


class TestHandleGate:
    def _make_state(self, tmp_path, status=RunStatus.GATED_INTENT):
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig(gates=[Gate.INTENT])
        state = RunState.create(source=source, config=config)
        state.status = status
        state.save(str(tmp_path))
        return state

    def test_tty_approve(self, tmp_path):
        state = self._make_state(tmp_path)
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.input", return_value="y"):
            mock_stdin.isatty.return_value = True
            result = _handle_gate(state, str(tmp_path), "intent",
                                  "Proceed? ", "aborted")
            assert result == "y"

    def test_tty_abort(self, tmp_path):
        state = self._make_state(tmp_path)
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.input", return_value="abort"):
            mock_stdin.isatty.return_value = True
            with pytest.raises(DarkFactoryError, match="aborted"):
                _handle_gate(state, str(tmp_path), "intent",
                             "Proceed? ", "aborted")

    def test_non_tty_exits_75(self, tmp_path, capsys):
        state = self._make_state(tmp_path)
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(SystemExit) as exc:
                _handle_gate(state, str(tmp_path), "intent",
                             "Proceed? ", "aborted")
            assert exc.value.code == EXIT_GATED

        captured = capsys.readouterr()
        gate_json = json.loads(captured.out.strip())
        assert gate_json["__gate__"] == "intent"
        assert gate_json["run_id"] == state.run_id
        assert "state_file" in gate_json


class TestPreflight:
    def test_git_available(self):
        missing = _preflight()
        assert "git" not in missing
