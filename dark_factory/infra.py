"""Infrastructure wrapper — worktree, agent launch, test verification."""

from __future__ import annotations

import atexit
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from .types import (
    DarkFactoryError,
    IntentDocument,
    RunState,
    SecurityPolicy,
    extract_sdk_result,
)
from .security import default_policy, build_permission_callback

# Track active worktrees for cleanup on exit
_active_worktrees: list[tuple[str, str, str]] = []  # (worktree_path, branch, repo_root)


# ---------------------------------------------------------------------------
# Worktree lifecycle
# ---------------------------------------------------------------------------

def create_worktree(repo_root: str, run_id: str, register_cleanup: bool = True) -> tuple[str, str]:
    """Create a git worktree for isolated implementation.

    Returns (worktree_path, branch_name).
    When register_cleanup is False, the worktree is NOT registered for atexit
    cleanup — the caller manages its lifecycle (used by phased flow).
    """
    repo_path = Path(repo_root)
    branch = f"dark-factory/{run_id}"
    worktree_path = str(repo_path.parent / f"{repo_path.name}-df-{run_id}")

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, worktree_path, "HEAD"],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        raise DarkFactoryError(f"Failed to create worktree: {result.stderr.strip()}")

    if register_cleanup:
        _active_worktrees.append((worktree_path, branch, repo_root))
    return worktree_path, branch


def remove_worktree(worktree_path: str, branch: str, repo_root: str) -> None:
    """Remove a worktree and its branch (normal completion cleanup)."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_path],
        capture_output=True, text=True, cwd=repo_root,
    )
    subprocess.run(
        ["git", "branch", "-D", branch],
        capture_output=True, text=True, cwd=repo_root,
    )


def _cleanup_worktree_only(worktree_path: str, repo_root: str) -> None:
    """Remove worktree directory but preserve the branch for crash recovery."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_path],
        capture_output=True, text=True, cwd=repo_root,
    )


def _cleanup_all_worktrees() -> None:
    """atexit handler — removes worktree dirs but preserves branches for recovery."""
    for worktree_path, _branch, repo_root in _active_worktrees:
        try:
            _cleanup_worktree_only(worktree_path, repo_root)
        except Exception:
            pass


atexit.register(_cleanup_all_worktrees)


def setup_workspace(state: RunState, repo_root: str) -> str:
    """Create worktree or in-place branch. Returns work_dir. Updates state in place.

    Does NOT register for atexit cleanup — caller manages worktree lifecycle.
    """
    if state.config.in_place:
        work_dir = repo_root
        branch = f"dark-factory/{state.run_id}"
        subprocess.run(
            ["git", "checkout", "-b", branch],
            capture_output=True, text=True, cwd=repo_root,
        )
        state.branch = branch
        state.worktree_path = repo_root
    else:
        work_dir, branch = create_worktree(repo_root, state.run_id, register_cleanup=False)
        state.worktree_path = work_dir
        state.branch = branch
    state.save(repo_root)
    return work_dir


# ---------------------------------------------------------------------------
# Test verification
# ---------------------------------------------------------------------------

def detect_test_command(repo_root: str) -> str:
    """Detect the test command for the project."""
    root = Path(repo_root)
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "python3 -m pytest"
    if (root / "package.json").exists():
        return "npm test"
    if (root / "Makefile").exists():
        return "make test"
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "go.mod").exists():
        return "go test ./..."
    return ""


def run_tests(test_command: str, cwd: str, timeout: int = 300) -> tuple[bool, str]:
    """Run the test command. Returns (passed, output)."""
    if not test_command:
        return True, "(no test command detected — skipping)"

    try:
        result = subprocess.run(
            shlex.split(test_command),
            capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Test command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Test command not found: {test_command}"


# ---------------------------------------------------------------------------
# Hooks isolation
# ---------------------------------------------------------------------------

def _create_no_hooks_settings() -> str:
    """Write a temp settings file that disables user hooks. Returns file path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="df-settings-")
    os.write(fd, b'{"hooks": {}}')
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Agent launch
# ---------------------------------------------------------------------------

IMPLEMENTATION_SYSTEM_PROMPT = """\
You are implementing a feature in a software project. You have full access to \
the codebase via Read, Edit, Write, Bash, Glob, and Grep tools.

Your approach:
1. Explore the codebase to understand the existing architecture and patterns
2. Plan your implementation approach
3. Implement the feature, following existing conventions
4. Write or update tests for your changes
5. Run tests to verify your implementation works
6. Make git commits for your work with clear commit messages

Follow the project's existing code style and conventions. If there is a CLAUDE.md \
file, read it first for project-specific instructions.
"""


def _build_implementation_prompt(intent: IntentDocument, work_dir: str) -> str:
    """Build the prompt for the implementation agent."""
    ac_text = "\n".join(f"  {i}. {ac}" for i, ac in enumerate(intent.acceptance_criteria, 1))
    return (
        f"# Feature: {intent.title}\n\n"
        f"{intent.summary}\n\n"
        f"## Acceptance Criteria\n{ac_text}\n\n"
        f"## Working Directory\n{work_dir}\n\n"
        f"Implement this feature. Start by reading CLAUDE.md if it exists, "
        f"then explore the codebase, implement the changes, write tests, "
        f"and verify everything works. Commit your work when done."
    )


async def _prompt_as_stream(prompt_text: str):
    """Wrap a string prompt as an AsyncIterable for streaming mode."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": prompt_text},
        "parent_tool_use_id": None,
        "session_id": None,
    }


async def _launch_agent(
    prompt: str,
    work_dir: str,
    policy: SecurityPolicy,
    max_turns: int = 30,
) -> tuple[str, float]:
    """Launch an Opus SDK agent. Returns (output_text, cost_usd)."""
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    can_use_tool = build_permission_callback(policy)
    settings_path = _create_no_hooks_settings()

    try:
        messages: list[Message] = []
        async for msg in query(
            prompt=_prompt_as_stream(prompt),
            options=ClaudeCodeOptions(
                system_prompt=IMPLEMENTATION_SYSTEM_PROMPT,
                model="claude-opus-4-20250514",
                max_turns=max_turns,
                cwd=work_dir,
                can_use_tool=can_use_tool,
                settings=settings_path,
            ),
        ):
            messages.append(msg)
    finally:
        try:
            os.unlink(settings_path)
        except OSError:
            pass

    return extract_sdk_result(messages)


async def _launch_fix_agent(
    test_output: str,
    work_dir: str,
    policy: SecurityPolicy,
) -> tuple[str, float]:
    """Launch a fix agent to address test failures. Returns (output, cost)."""
    prompt = (
        "The tests are failing after implementation. Fix the failures.\n\n"
        f"## Test Output\n```\n{test_output[-3000:]}\n```\n\n"
        "Fix the failing tests, then run the test suite to verify your fixes work. "
        "Commit your fixes."
    )
    return await _launch_agent(prompt, work_dir, policy, max_turns=15)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def run_implementation(
    state: RunState,
    intent: IntentDocument,
    repo_root: str,
) -> str:
    """Run the full implementation cycle: worktree -> agent -> test -> diff.

    Returns the git diff of all changes.
    """
    # Determine working directory
    work_dir = setup_workspace(state, repo_root)
    # Re-register for atexit cleanup (monolithic flow owns the full lifecycle)
    if not state.config.in_place:
        _active_worktrees.append((state.worktree_path, state.branch, repo_root))

    # Build security policy with write boundary
    policy = default_policy(write_boundary=Path(work_dir))

    # Launch implementation agent
    print(f"  Launching Opus agent in {work_dir}")
    start = time.time()
    prompt = _build_implementation_prompt(intent, work_dir)
    output, cost = await _launch_agent(prompt, work_dir, policy)
    elapsed = time.time() - start
    state.cost_usd += cost
    print(f"  Agent complete ({elapsed:.0f}s, ${cost:.4f})")

    # Budget check after implementation
    budget_exceeded = state.cost_usd >= state.config.max_cost_usd
    if budget_exceeded:
        print(f"  Budget exceeded (${state.cost_usd:.2f} >= ${state.config.max_cost_usd:.2f})")

    # Hybrid test verification
    test_cmd = state.test_command or detect_test_command(work_dir)
    if test_cmd:
        print(f"  Running tests: {test_cmd}")
        passed, test_output = run_tests(test_cmd, work_dir)

        if not passed and not budget_exceeded:
            print("  Tests failed — launching fix agent (1 retry)")
            fix_output, fix_cost = await _launch_fix_agent(test_output, work_dir, policy)
            state.cost_usd += fix_cost

            # Re-run tests
            passed, test_output = run_tests(test_cmd, work_dir)
            if passed:
                print("  Tests pass after fix")
            else:
                print("  Tests still failing — proceeding to evaluation with failures")
        elif not passed and budget_exceeded:
            print("  Tests failed — skipping fix retry (budget exceeded)")
        else:
            print("  Tests pass")

    # Capture diff
    diff_result = subprocess.run(
        ["git", "diff", f"{state.base_branch}...HEAD"],
        capture_output=True, text=True, cwd=work_dir,
    )
    diff = diff_result.stdout

    if not diff.strip():
        # Try unstaged changes
        diff_result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, cwd=work_dir,
        )
        diff = diff_result.stdout

    return diff
