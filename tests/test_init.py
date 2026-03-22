"""Tests for ``dark-factory init`` subcommand."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_init_creates_command_file(tmp_path: Path) -> None:
    """init writes .claude/commands/dark-factory.md in a git repo."""
    # Set up a bare git repo
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    from dark_factory.init import run_init

    run_init(str(tmp_path))

    cmd_file = tmp_path / ".claude" / "commands" / "dark-factory.md"
    assert cmd_file.exists()
    content = cmd_file.read_text()
    assert "/dark-factory" in content
    assert "$ARGUMENTS" in content


def test_init_adds_gitignore_entry(tmp_path: Path) -> None:
    """init ensures .dark-factory/ is in .gitignore."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    from dark_factory.init import run_init

    run_init(str(tmp_path))

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert ".dark-factory/" in gitignore.read_text().splitlines()


def test_init_preserves_existing_gitignore(tmp_path: Path) -> None:
    """init appends to existing .gitignore without clobbering."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n")

    from dark_factory.init import run_init

    run_init(str(tmp_path))

    lines = gitignore.read_text().splitlines()
    assert "node_modules/" in lines
    assert ".dark-factory/" in lines


def test_init_idempotent(tmp_path: Path) -> None:
    """Running init twice doesn't duplicate the gitignore entry."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    from dark_factory.init import run_init

    run_init(str(tmp_path))
    run_init(str(tmp_path))

    gitignore = tmp_path / ".gitignore"
    lines = gitignore.read_text().splitlines()
    assert lines.count(".dark-factory/") == 1


def test_init_rejects_non_git_dir(tmp_path: Path) -> None:
    """init exits with error if target is not a git repo."""
    import pytest

    with pytest.raises(SystemExit):
        from dark_factory.init import run_init

        run_init(str(tmp_path))
