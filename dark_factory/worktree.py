"""Worktree management for parallel task execution.

Creates and cleans up temporary git worktrees so parallel agents
can work on isolated branches without file conflicts.
"""

from __future__ import annotations

import atexit
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Registry for atexit cleanup
_active_worktrees: list[tuple[str, str]] = []  # (worktree_path, branch_name)


@dataclass
class ParallelWorktree:
    """A temporary worktree for a parallel agent."""
    worktree_path: str
    branch_name: str
    repo_root: str


def create_parallel_worktree(
    repo_root: str,
    issue_id: str,
    *,
    dry_run: bool = False,
) -> ParallelWorktree:
    """Create a temporary git worktree for a parallel agent.

    Creates a worktree at `<repo_parent>/<repo_name>-parallel-<issue_id>`
    on branch `parallel/<issue_id>`.
    """
    branch_name = f"parallel/{issue_id}"
    repo_path = Path(repo_root)
    worktree_path = str(
        repo_path.parent / f"{repo_path.name}-parallel-{issue_id}"
    )

    if dry_run:
        return ParallelWorktree(
            worktree_path=worktree_path,
            branch_name=branch_name,
            repo_root=repo_root,
        )

    # Create the worktree with a new branch from HEAD
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, worktree_path, "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    # Register for atexit cleanup
    _active_worktrees.append((worktree_path, branch_name))

    return ParallelWorktree(
        worktree_path=worktree_path,
        branch_name=branch_name,
        repo_root=repo_root,
    )


def remove_parallel_worktree(
    worktree_path: str,
    branch_name: str,
    repo_root: str,
) -> None:
    """Remove a parallel worktree and its branch.

    Safe to call multiple times -- silently succeeds if already removed.
    Uses try/finally to ensure branch cleanup even if worktree removal fails.
    """
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    finally:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Remove from registry
        entry = (worktree_path, branch_name)
        if entry in _active_worktrees:
            _active_worktrees.remove(entry)


def _cleanup_all_worktrees() -> None:
    """Atexit handler: remove any remaining parallel worktrees.

    Called on unexpected exit to prevent leaking worktrees and branches.
    Iterates a copy of the list since remove_parallel_worktree modifies it.
    """
    for worktree_path, branch_name in list(_active_worktrees):
        try:
            # Infer repo_root from the git worktree list in the parent dir
            wt_path = Path(worktree_path)
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(wt_path.parent),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # First "worktree" line is the main worktree
                for line in result.stdout.splitlines():
                    if line.startswith("worktree "):
                        main_wt = line.split(" ", 1)[1]
                        remove_parallel_worktree(worktree_path, branch_name, main_wt)
                        break
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass


# Register the atexit handler
atexit.register(_cleanup_all_worktrees)
