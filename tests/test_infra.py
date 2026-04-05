"""Tests for dark_factory.infra."""

import subprocess
import pytest
from pathlib import Path

from dark_factory.infra import (
    detect_test_command,
    run_tests,
    create_worktree,
    remove_worktree,
    _cleanup_worktree_only,
    _build_implementation_prompt,
    _create_no_hooks_settings,
)
from dark_factory.types import IntentDocument


class TestDetectTestCommand:
    def test_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        assert detect_test_command(str(tmp_path)) == "python3 -m pytest"

    def test_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert detect_test_command(str(tmp_path)) == "npm test"

    def test_make_project(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\techo ok")
        assert detect_test_command(str(tmp_path)) == "make test"

    def test_rust_project(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\nname='x'")
        assert detect_test_command(str(tmp_path)) == "cargo test"

    def test_go_project(self, tmp_path):
        (tmp_path / "go.mod").write_text("module x")
        assert detect_test_command(str(tmp_path)) == "go test ./..."

    def test_unknown_project(self, tmp_path):
        assert detect_test_command(str(tmp_path)) == ""


class TestRunTests:
    def test_no_test_command_skips(self, tmp_path):
        passed, output = run_tests("", str(tmp_path))
        assert passed
        assert "skipping" in output.lower()

    def test_passing_command(self, tmp_path):
        passed, output = run_tests("echo ok", str(tmp_path))
        assert passed

    def test_failing_command(self, tmp_path):
        passed, output = run_tests("false", str(tmp_path))
        assert not passed


class TestWorktree:
    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a minimal git repo for worktree tests."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        return repo

    def test_create_and_remove(self, git_repo):
        worktree_path, branch = create_worktree(str(git_repo), "test123")
        assert Path(worktree_path).exists()
        assert "test123" in branch

        remove_worktree(worktree_path, branch, str(git_repo))
        assert not Path(worktree_path).exists()

    def test_worktree_has_files(self, git_repo):
        worktree_path, branch = create_worktree(str(git_repo), "test456")
        assert (Path(worktree_path) / "README.md").exists()
        remove_worktree(worktree_path, branch, str(git_repo))


class TestBuildImplementationPrompt:
    def test_includes_intent(self):
        intent = IntentDocument("Add Login", "JWT auth", ["Returns 200"])
        prompt = _build_implementation_prompt(intent, "/tmp/work")
        assert "Add Login" in prompt
        assert "Returns 200" in prompt
        assert "/tmp/work" in prompt


class TestCleanupWorktreeOnly:
    @pytest.fixture
    def git_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        return repo

    def test_preserves_branch(self, git_repo):
        """Crash cleanup removes worktree dir but preserves the branch."""
        worktree_path, branch = create_worktree(str(git_repo), "crash-test")
        assert Path(worktree_path).exists()

        _cleanup_worktree_only(worktree_path, str(git_repo))
        assert not Path(worktree_path).exists()

        # Branch should still exist
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            capture_output=True, text=True, cwd=git_repo,
        )
        assert branch in result.stdout


class TestNoHooksSettings:
    def test_creates_temp_file_with_hooks_disabled(self):
        import json
        import os
        path = _create_no_hooks_settings()
        try:
            assert os.path.exists(path)
            with open(path) as f:
                parsed = json.load(f)
            assert parsed == {"hooks": {}}
        finally:
            os.unlink(path)
