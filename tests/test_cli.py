"""Tests for dark_factory.__main__ CLI."""

import subprocess
import sys
import pytest

from dark_factory.__main__ import (
    build_parser,
    _preflight,
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


class TestPreflight:
    def test_git_available(self):
        missing = _preflight()
        assert "git" not in missing
