"""Verification phases: Phase 8 (test verification) and Phase 10 (local dev).

Phase 8 detects the test command, runs autofix tooling, executes tests,
and on failure calls an SDK fix agent (opus, max_turns=15) with up to 2 retries.

Phase 10 detects the dev server command, starts the process, and renders a
verification checklist for the human.  Zero LLM tokens consumed.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8: Test Verification
# ═══════════════════════════════════════════════════════════════════════════════

# Test command detection patterns from CLAUDE.md / project files
_TEST_COMMAND_PATTERNS = [
    re.compile(r"(?:npm|yarn|pnpm)\s+(?:run\s+)?test\b"),
    re.compile(r"pytest\b"),
    re.compile(r"python3?\s+-m\s+pytest\b"),
    re.compile(r"make\s+test\b"),
    re.compile(r"cargo\s+test\b"),
    re.compile(r"go\s+test\b"),
    re.compile(r"vitest\b"),
    re.compile(r"jest\b"),
]

# Autofix commands indexed by what file/tool exists in the project
_AUTOFIX_COMMANDS: dict[str, list[str]] = {
    "package.json": ["npx", "eslint", "--fix", "."],
    ".eslintrc.json": ["npx", "eslint", "--fix", "."],
    ".eslintrc.js": ["npx", "eslint", "--fix", "."],
    "pyproject.toml": ["python3", "-m", "black", "."],
    "setup.cfg": ["python3", "-m", "black", "."],
}

# Fallback test commands by project file presence
_FALLBACK_TEST_COMMANDS: dict[str, str] = {
    "package.json": "npm test",
    "yarn.lock": "yarn test",
    "pnpm-lock.yaml": "pnpm test",
    "pytest.ini": "pytest",
    "conftest.py": "pytest",
    "pyproject.toml": "pytest",
    "Makefile": "make test",
    "Cargo.toml": "cargo test",
    "go.mod": "go test ./...",
}

MAX_TEST_RETRIES = 2


@dataclass
class HoldoutResult:
    """Outcome of hold-out test execution (Phase 8 extension)."""

    passed: bool = True
    failures: list[str] = field(default_factory=list)
    severity: str = "WARNING"


@dataclass
class SingleTestResult:
    """Outcome of a test run."""

    passed: bool
    output: str = ""
    command: str = ""
    return_code: int = 0


@dataclass
class VerificationResult:
    """Outcome of the full Phase 8 verification loop."""

    passed: bool
    test_command: str = ""
    attempts: int = 0
    fix_cost_usd: float = 0.0
    final_output: str = ""


def detect_test_command(
    worktree_path: str, claude_md_text: str = ""
) -> str | None:
    """Detect the project's test command from CLAUDE.md or project files."""
    wt = Path(worktree_path)

    # Check CLAUDE.md first
    if claude_md_text:
        for pattern in _TEST_COMMAND_PATTERNS:
            match = pattern.search(claude_md_text)
            if match:
                return match.group(0)

    # Check package.json test scripts
    pkg_path = wt / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
            scripts = pkg.get("scripts", {})
            for key in ("test", "test:unit", "test:e2e"):
                if key in scripts:
                    return f"npm run {key}" if ":" in key else "npm test"
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback to project file detection
    for filename, cmd in _FALLBACK_TEST_COMMANDS.items():
        if (wt / filename).exists():
            return cmd

    return None


def run_autofix(worktree_path: str) -> bool:
    """Run autofix tools (eslint --fix, black, etc.) before LLM intervention.

    Returns True if an autofix command was found and executed.
    """
    wt = Path(worktree_path)

    for marker_file, cmd_parts in _AUTOFIX_COMMANDS.items():
        if (wt / marker_file).exists():
            try:
                subprocess.run(
                    cmd_parts,
                    cwd=worktree_path,
                    capture_output=True,
                    timeout=60,
                )
                return True
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue

    return False


def run_tests(worktree_path: str, test_command: str) -> SingleTestResult:
    """Execute the test command and return the result."""
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return SingleTestResult(
            passed=result.returncode == 0,
            output=(result.stdout + "\n" + result.stderr).strip(),
            command=test_command,
            return_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return SingleTestResult(
            passed=False,
            output=f"Test command timed out after 300s: {test_command}",
            command=test_command,
            return_code=-1,
        )
    except FileNotFoundError:
        return SingleTestResult(
            passed=False,
            output=f"Test command not found: {test_command}",
            command=test_command,
            return_code=-1,
        )


def run_holdout_tests(
    worktree_path: str,
    holdout_test_paths: list[str],
) -> HoldoutResult:
    """Execute each hold-out test file individually, collect pass/fail."""
    result = HoldoutResult()

    if not holdout_test_paths:
        return result

    for test_path in holdout_test_paths:
        if not Path(test_path).exists():
            result.failures.append(f"Hold-out test file not found: {test_path}")
            result.passed = False
            continue

        try:
            proc = subprocess.run(
                ["python3", "-m", "pytest", test_path, "-v"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=120,
            )
            if proc.returncode != 0:
                result.passed = False
                result.failures.append(
                    f"{test_path}: {proc.stdout[-500:]}{proc.stderr[-500:]}"
                )
        except subprocess.TimeoutExpired:
            result.passed = False
            result.failures.append(f"{test_path}: timed out after 120s")
        except FileNotFoundError:
            result.passed = False
            result.failures.append(f"{test_path}: pytest not found")

    return result


async def verify_tests(
    worktree_path: str,
    claude_md_text: str = "",
    *,
    dry_run: bool = False,
    holdout_test_paths: list[str] | None = None,
) -> tuple[VerificationResult, HoldoutResult | None]:
    """Phase 8: full test verification loop with autofix and SDK fix retries.

    1. Detect test command
    2. Run autofix (eslint --fix, black, etc.) before LLM
    3. Run tests
    4. On failure: call SDK fix agent (opus, max_turns=15), max 2 retries
    """
    test_cmd = detect_test_command(worktree_path, claude_md_text)

    if not test_cmd:
        return VerificationResult(
            passed=True,
            test_command="",
            attempts=0,
            final_output="No test command detected — skipping test verification.",
        ), None

    if dry_run:
        return VerificationResult(
            passed=True,
            test_command=test_cmd,
            attempts=0,
            final_output="[dry-run] test verification skipped",
        ), None

    # Run autofix before testing
    run_autofix(worktree_path)

    total_cost = 0.0
    verification = None

    for attempt in range(1, MAX_TEST_RETRIES + 1):
        result = run_tests(worktree_path, test_cmd)

        if result.passed:
            verification = VerificationResult(
                passed=True,
                test_command=test_cmd,
                attempts=attempt,
                fix_cost_usd=total_cost,
                final_output=result.output,
            )
            break

        # Tests failed — call SDK fix agent
        from .agents import call_fix

        fix_prompt = (
            f"Tests failed (attempt {attempt}/{MAX_TEST_RETRIES}). "
            f"Test command: `{test_cmd}`\n\n"
            f"Test output:\n```\n{result.output[-3000:]}\n```\n\n"
            f"Analyze the failures and fix the code. "
            f"Do NOT modify the tests unless they are clearly wrong. "
            f"After fixing, the tests should pass when run with: {test_cmd}"
        )

        fix_output, fix_cost, _fix_turns = await call_fix(
            fix_prompt,
            worktree_path=worktree_path,
            system_prompt=(
                "You are a test-fix agent. Analyze test failures and fix the "
                "source code to make tests pass. Focus on the root cause. "
                "Do not add debug logging or skip tests."
            ),
        )
        total_cost += fix_cost

    if verification is None:
        # Final attempt after last fix
        final_result = run_tests(worktree_path, test_cmd)
        verification = VerificationResult(
            passed=final_result.passed,
            test_command=test_cmd,
            attempts=MAX_TEST_RETRIES,
            fix_cost_usd=total_cost,
            final_output=final_result.output,
        )

    # Run hold-out tests after main suite passes
    holdout = None
    if verification.passed and holdout_test_paths:
        holdout = run_holdout_tests(worktree_path, holdout_test_paths)

    return verification, holdout


# ═══════════════════════════════════════════════════════════════════════════════
# Hold-out warning presentation (post-Phase 8)
# ═══════════════════════════════════════════════════════════════════════════════


class HoldoutDecision:
    """Enum-like constants for holdout warning responses."""

    ACCEPT = "accept"
    INVESTIGATE = "investigate"
    ABORT = "abort"


def render_holdout_warning(holdout: HoldoutResult) -> str:
    """Format holdout test failures for human review.

    Mirrors the checkpoint.render_checkpoint() pattern: presents results
    and offers accept/investigate/abort choices.
    """
    if holdout.passed:
        return (
            "Hold-out tests: ALL PASSED\n"
            "No hidden-test regressions detected."
        )

    failure_lines = "\n".join(f"  - {f}" for f in holdout.failures)

    return f"""\
{'=' * 45}
DARK FACTORY — Hold-out Test Warning
{'=' * 45}

Severity: {holdout.severity}
Hold-out tests found {len(holdout.failures)} failure(s):

{failure_lines}

These tests were hidden from the implementation agent.
Failures may indicate the implementation does not fully
satisfy the spec's edge cases or boundary conditions.

{'=' * 45}

(A) Accept — proceed despite hold-out failures
(B) Investigate — pause pipeline for manual review
(C) Abort — stop the pipeline"""


def parse_holdout_decision(response: str) -> str:
    """Map a human response string to a HoldoutDecision constant.

    Accepts the letter (A/B/C) or the word (accept/investigate/abort),
    case-insensitive.
    """
    cleaned = response.strip().lower()

    if cleaned in ("a", "accept"):
        return HoldoutDecision.ACCEPT
    if cleaned in ("b", "investigate"):
        return HoldoutDecision.INVESTIGATE
    if cleaned in ("c", "abort"):
        return HoldoutDecision.ABORT

    raise ValueError(
        f"Unrecognized response: {response!r}. "
        "Expected A/B/C or accept/investigate/abort."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10: Local Dev Verification
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns to detect dev server commands from CLAUDE.md or package.json
_DEV_COMMAND_PATTERNS = [
    re.compile(r"(?:npm|yarn|pnpm)\s+run\s+dev\b"),
    re.compile(r"(?:yarn|pnpm)\s+dev\b"),
    re.compile(r"(?:npm|yarn|pnpm)\s+start\b"),
    re.compile(r"python3?\s+(?:-m\s+)?(?:uvicorn|flask|manage\.py\s+runserver)\b"),
    re.compile(r"\./start-local\.sh\b"),
    re.compile(r"make\s+(?:dev|start|serve)\b"),
    re.compile(r"cargo\s+run\b"),
    re.compile(r"go\s+run\b"),
]

# URL patterns to detect default ports
_URL_PATTERNS = [
    re.compile(r"https?://localhost:\d+"),
    re.compile(r"https?://127\.0\.0\.1:\d+"),
]

# Fallback dev commands by package manager / framework
_FALLBACK_COMMANDS: dict[str, str] = {
    "package.json": "npm run dev",
    "yarn.lock": "yarn dev",
    "pnpm-lock.yaml": "pnpm dev",
    "Makefile": "make dev",
    "Cargo.toml": "cargo run",
    "go.mod": "go run .",
    "manage.py": "python3 manage.py runserver",
}


@dataclass
class DevServerInfo:
    """Result of dev server detection."""

    command: str | None = None
    url: str = "http://localhost:3000"
    detected_from: str = ""


def detect_dev_command(worktree_path: str, claude_md_text: str = "") -> DevServerInfo:
    """Detect the local dev server command from project files.

    Checks CLAUDE.md content first, then falls back to detecting
    lock files / config files in the worktree.
    """
    info = DevServerInfo()
    wt = Path(worktree_path)

    # Search CLAUDE.md for dev commands
    if claude_md_text:
        for pattern in _DEV_COMMAND_PATTERNS:
            match = pattern.search(claude_md_text)
            if match:
                info.command = match.group(0)
                info.detected_from = "CLAUDE.md"
                break

        # Extract URL from CLAUDE.md
        for pattern in _URL_PATTERNS:
            match = pattern.search(claude_md_text)
            if match:
                info.url = match.group(0)
                break

    # Fall back to lock/config file detection
    if not info.command:
        for filename, cmd in _FALLBACK_COMMANDS.items():
            if (wt / filename).exists():
                info.command = cmd
                info.detected_from = filename
                break

    # Try to extract port from package.json scripts
    if not info.command or info.detected_from == "package.json":
        pkg_path = wt / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                scripts = pkg.get("scripts", {})
                for key in ("dev", "start", "serve"):
                    if key in scripts:
                        if not info.command:
                            info.command = f"npm run {key}"
                            info.detected_from = f"package.json scripts.{key}"
                        # Look for port in script value
                        port_match = re.search(r"--port\s+(\d+)", scripts[key])
                        if port_match:
                            info.url = f"http://localhost:{port_match.group(1)}"
                        break
            except (json.JSONDecodeError, OSError):
                pass

    return info


def render_verification_checklist(
    dev_info: DevServerInfo,
    worktree_path: str,
    check_items: list[str],
) -> str:
    """Render the Phase 10 verification prompt for the human."""
    if not dev_info.command:
        return (
            f"No dev server command detected in worktree: {worktree_path}\n"
            "Skipping local dev verification.\n"
            "When you're satisfied with the changes, let me know and I'll create the PR."
        )

    checks = "\n".join(f"  - [ ] {item}" for item in check_items)

    return f"""\
Local dev server started in worktree: {worktree_path}
Command: {dev_info.command} (detected from {dev_info.detected_from})
URL: {dev_info.url}

To verify the changes, check:
{checks}

When you're satisfied, let me know and I'll create the PR."""


def start_dev_server(
    worktree_path: str,
    command: str,
    dry_run: bool = False,
) -> subprocess.Popen | None:
    """Start the dev server as a background process.

    Returns the Popen handle, or None in dry-run mode.
    """
    if dry_run:
        return None

    return subprocess.Popen(
        command,
        shell=True,
        cwd=worktree_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
