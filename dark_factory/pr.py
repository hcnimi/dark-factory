"""Phase 11: push, PR creation, and worktree cleanup.

Pushes the branch, generates a PR body via SDK (sonnet, max_turns=3, no tools),
creates the PR with gh, removes the worktree, and closes beads issues.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PRResult:
    """Outcome of Phase 11."""

    pr_url: str = ""
    branch: str = ""
    cost_usd: float = 0.0
    closed_issues: list[str] = field(default_factory=list)


def _run_git(args: list[str], cwd: str, *, timeout: int = 30) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def push_branch(worktree_path: str, branch: str) -> None:
    """Push the feature branch to origin."""
    _run_git(["push", "-u", "origin", branch], cwd=worktree_path, timeout=60)


def get_diff_summary(worktree_path: str) -> str:
    """Get a summary of changes on the branch vs main."""
    try:
        return _run_git(
            ["diff", "--stat", "main...HEAD"],
            cwd=worktree_path,
        )
    except RuntimeError:
        # Branch might not have main as ancestor
        return _run_git(["diff", "--stat", "HEAD~1"], cwd=worktree_path)


def get_diff(worktree_path: str) -> str:
    """Get the full diff of changes on the branch vs main."""
    try:
        return _run_git(["diff", "main...HEAD"], cwd=worktree_path)
    except RuntimeError:
        return _run_git(["diff", "HEAD~1"], cwd=worktree_path)


async def generate_pr_body(
    diff_summary: str,
    source_id: str,
    summary: str,
    external_ref: str,
    change_id: str,
    *,
    dry_run: bool = False,
) -> tuple[str, float]:
    """Generate a PR body using the SDK (sonnet, max_turns=3, no tools).

    Returns (pr_body, cost_usd).
    """
    if dry_run:
        return (
            f"## Summary\n{summary}\n\n"
            f"**Source**: {external_ref}\n\n"
            f"## Changes\n{diff_summary}\n\n"
            f"---\nAutomated by `/dark-factory`",
            0.0,
        )

    from .agents import call_pr_body

    prompt = (
        f"Generate a concise PR description for these changes.\n\n"
        f"Source: {external_ref}\n"
        f"Summary: {summary}\n"
        f"OpenSpec change: openspec/changes/{change_id}/\n\n"
        f"Diff summary:\n```\n{diff_summary}\n```\n\n"
        f"Format:\n"
        f"## Summary\n"
        f"<1-2 sentence overview>\n\n"
        f"**Source**: {external_ref}\n"
        f"**OpenSpec**: `openspec/changes/{change_id}/`\n\n"
        f"## Changes\n"
        f"<bulleted list of what was changed and why>\n\n"
        f"## Test Plan\n"
        f"<bulleted checklist of how to verify>\n\n"
        f"---\n"
        f"Automated by `/dark-factory`\n\n"
        f"Output ONLY the PR body text, no code fences or extra commentary."
    )

    body, cost, _turns = await call_pr_body(prompt)
    return body, cost


def create_pr(
    worktree_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    dry_run: bool = False,
) -> str:
    """Create a PR using gh and return the PR URL."""
    if dry_run:
        return "https://github.com/example/repo/pull/0"

    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch,
        ],
        capture_output=True,
        text=True,
        cwd=worktree_path,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh pr create failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def remove_worktree(repo_root: str, worktree_path: str) -> None:
    """Remove the worktree (branch is preserved for the PR)."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", worktree_path],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def close_issues(issue_ids: list[str], reason: str, *, dry_run: bool = False) -> list[str]:
    """Close beads issues with the given reason. Returns IDs successfully closed."""
    if dry_run:
        return list(issue_ids)

    closed: list[str] = []
    for issue_id in issue_ids:
        try:
            subprocess.run(
                ["bd", "close", issue_id, "--reason", reason],
                capture_output=True,
                text=True,
                timeout=15,
            )
            closed.append(issue_id)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
    return closed


def cleanup_state_file(repo_root: str, source_id: str) -> None:
    """Delete the progress/state file after successful PR creation."""
    state_dir = Path(repo_root) / ".dark-factory"
    state_file = state_dir / f"{source_id}.json"
    if state_file.exists():
        state_file.unlink()
    # Also check .md format from older sessions
    md_file = state_dir / f"{source_id}.md"
    if md_file.exists():
        md_file.unlink()
    # Remove dir if empty
    if state_dir.exists() and not any(state_dir.iterdir()):
        state_dir.rmdir()


async def run_phase_11(
    repo_root: str,
    worktree_path: str,
    branch: str,
    source_id: str,
    summary: str,
    external_ref: str,
    issue_ids: list[str],
    *,
    dry_run: bool = False,
) -> PRResult:
    """Full Phase 11 execution: push, PR body, create PR, cleanup.

    Returns PRResult with the PR URL and cost.
    """
    result = PRResult(branch=branch)

    # Push branch
    if not dry_run:
        push_branch(worktree_path, branch)

    # Generate PR body
    change_id = f"dark-factory-{source_id}"
    diff_summary = "" if dry_run else get_diff_summary(worktree_path)

    pr_body, body_cost = await generate_pr_body(
        diff_summary,
        source_id,
        summary,
        external_ref,
        change_id,
        dry_run=dry_run,
    )
    result.cost_usd += body_cost

    # Create PR
    pr_title = f"{source_id}: {summary}"
    pr_url = create_pr(
        worktree_path, branch, pr_title, pr_body, dry_run=dry_run
    )
    result.pr_url = pr_url

    # Remove worktree (branch preserved for PR)
    if not dry_run:
        remove_worktree(repo_root, worktree_path)

    # Close issues
    if issue_ids:
        closed = close_issues(
            issue_ids, f"PR: {pr_url}", dry_run=dry_run
        )
        result.closed_issues = closed

    # Cleanup state file
    cleanup_state_file(repo_root, source_id)

    return result
