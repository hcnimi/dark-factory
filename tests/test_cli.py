"""Tests for dark_factory.__main__ CLI."""

import argparse
import json
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from dark_factory.__main__ import (
    build_parser,
    cmd_prepare,
    cmd_verify,
    cmd_complete,
    _load_state,
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


class TestBuildParserNewSubcommands:
    def test_prepare_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["prepare", "abc123"])
        assert args.command == "prepare"
        assert args.run_id == "abc123"

    def test_verify_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["verify", "abc123"])
        assert args.command == "verify"
        assert args.run_id == "abc123"

    def test_complete_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["complete", "abc123"])
        assert args.command == "complete"
        assert args.run_id == "abc123"

    def test_evaluate_with_run(self):
        parser = build_parser()
        args = parser.parse_args(["evaluate", "--run", "abc123"])
        assert args.command == "evaluate"
        assert args.run == "abc123"
        assert args.branch is None

    def test_evaluate_with_branch_still_works(self):
        parser = build_parser()
        args = parser.parse_args(["evaluate", "feature/login"])
        assert args.branch == "feature/login"
        assert args.run is None


class TestLoadState:
    def _make_state(self, tmp_path, status=RunStatus.GATED_INTENT):
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig(gates=[Gate.INTENT])
        state = RunState.create(source=source, config=config)
        state.status = status
        state.save(str(tmp_path))
        return state

    def test_load_valid_state(self, tmp_path):
        state = self._make_state(tmp_path)
        loaded = _load_state(str(tmp_path), state.run_id, [RunStatus.GATED_INTENT])
        assert loaded.run_id == state.run_id

    def test_wrong_status_exits(self, tmp_path):
        state = self._make_state(tmp_path, RunStatus.PENDING)
        with pytest.raises(SystemExit):
            _load_state(str(tmp_path), state.run_id, [RunStatus.GATED_INTENT])

    def test_missing_state_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            _load_state(str(tmp_path), "nonexistent", [RunStatus.GATED_INTENT])


class TestCmdPrepare:
    def _make_gated_state(self, tmp_path):
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig(gates=[Gate.INTENT])
        state = RunState.create(source=source, config=config)
        state.status = RunStatus.GATED_INTENT
        state.intent = IntentDocument("Test Feature", "Do the thing", ["It works"])
        state.save(str(tmp_path))
        return state

    def test_prepare_transitions_to_prepared(self, tmp_path, capsys):
        state = self._make_gated_state(tmp_path)
        args = argparse.Namespace(run_id=state.run_id)

        with patch("dark_factory.__main__._get_repo_root", return_value=str(tmp_path)), \
             patch("dark_factory.infra.setup_workspace", return_value=str(tmp_path / "work")):
            cmd_prepare(args)

        reloaded = RunState.load(state.state_path(str(tmp_path)))
        assert reloaded.status == RunStatus.PREPARED

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["run_id"] == state.run_id
        assert "prompt_file" in output
        assert "system_prompt_file" in output

    def test_prepare_writes_prompt_files(self, tmp_path):
        state = self._make_gated_state(tmp_path)
        args = argparse.Namespace(run_id=state.run_id)

        with patch("dark_factory.__main__._get_repo_root", return_value=str(tmp_path)), \
             patch("dark_factory.infra.setup_workspace", return_value=str(tmp_path / "work")):
            cmd_prepare(args)

        assert state.prompt_path(str(tmp_path)).exists()
        assert state.system_prompt_path(str(tmp_path)).exists()
        assert "Test Feature" in state.prompt_path(str(tmp_path)).read_text()


class TestCmdVerify:
    def _make_prepared_state(self, tmp_path):
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig()
        state = RunState.create(source=source, config=config)
        state.status = RunStatus.PREPARED
        state.worktree_path = str(tmp_path)
        state.base_branch = "main"
        state.save(str(tmp_path))
        return state

    def test_verify_outputs_json(self, tmp_path, capsys):
        state = self._make_prepared_state(tmp_path)
        args = argparse.Namespace(run_id=state.run_id)

        with patch("dark_factory.__main__._get_repo_root", return_value=str(tmp_path)), \
             patch("dark_factory.infra.run_tests", return_value=(True, "all passed")), \
             patch("subprocess.run") as mock_run:
            # Mock git diff
            mock_run.return_value.stdout = "diff --git a/foo\n+bar\n"
            mock_run.return_value.returncode = 0
            cmd_verify(args)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["tests_passed"] is True
        assert output["run_id"] == state.run_id

    def test_verify_allows_retry(self, tmp_path, capsys):
        """VERIFYING status is accepted — enables retry loops."""
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig()
        state = RunState.create(source=source, config=config)
        state.status = RunStatus.VERIFYING
        state.worktree_path = str(tmp_path)
        state.base_branch = "main"
        state.save(str(tmp_path))
        args = argparse.Namespace(run_id=state.run_id)

        with patch("dark_factory.__main__._get_repo_root", return_value=str(tmp_path)), \
             patch("dark_factory.infra.run_tests", return_value=(True, "ok")), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "diff\n"
            mock_run.return_value.returncode = 0
            cmd_verify(args)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["tests_passed"] is True


class TestCmdComplete:
    def _make_gated_eval_state(self, tmp_path):
        source = SourceInfo(SourceKind.INLINE, "test", "test")
        config = RunConfig(gates=[Gate.EVAL])
        state = RunState.create(source=source, config=config)
        state.status = RunStatus.GATED_EVAL
        state.branch = "dark-factory/test"
        state.worktree_path = ""  # no worktree to clean
        state.save(str(tmp_path))
        return state

    def test_complete_transitions(self, tmp_path, capsys):
        state = self._make_gated_eval_state(tmp_path)
        args = argparse.Namespace(run_id=state.run_id)

        with patch("dark_factory.__main__._get_repo_root", return_value=str(tmp_path)):
            cmd_complete(args)

        reloaded = RunState.load(state.state_path(str(tmp_path)))
        assert reloaded.status == RunStatus.COMPLETE

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["status"] == "complete"


class TestPreflight:
    def test_git_available(self):
        missing = _preflight()
        assert "git" not in missing
