"""Phases 3 and 4: branch/worktree setup, openspec scaffold, and plan review.

Phase 3 creates the feature branch, worktree, installs dependencies, and
generates openspec change files (proposal.md, spec.md, tasks.md) via SDK.

Phase 4 spawns a review agent to check the plan for completeness and
feasibility, then commits the openspec change files.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .state import PipelineState


# ---------------------------------------------------------------------------
# Phase 3 data types
# ---------------------------------------------------------------------------

@dataclass
class WorktreeInfo:
    """Result of branch/worktree creation."""

    worktree_path: str = ""
    branch: str = ""
    change_id: str = ""
    repo_root: str = ""


@dataclass
class ScaffoldResult:
    """Full outcome of Phase 3."""

    worktree: WorktreeInfo = field(default_factory=WorktreeInfo)
    deps_installed: bool = False
    openspec_validated: bool = False
    scaffold_cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Phase 4 data types
# ---------------------------------------------------------------------------

@dataclass
class ReviewFinding:
    """A single issue found during plan review."""

    category: str  # "coverage", "feasibility", "edge_case", "scope_creep"
    description: str


@dataclass
class PlanReviewResult:
    """Outcome of Phase 4 plan review."""

    verdict: str = "PASS"  # "PASS" or "NEEDS_WORK"
    findings: list[ReviewFinding] = field(default_factory=list)
    review_output: str = ""
    review_cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Git / shell helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str, *, timeout: int = 30) -> str:
    """Run a git command and return stdout. Raises RuntimeError on failure."""
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


def _run_cmd(args: list[str], cwd: str, *, timeout: int = 60) -> tuple[int, str, str]:
    """Run any command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out: {' '.join(args)}"


# ---------------------------------------------------------------------------
# Phase 3: Branch, Worktree, Dependencies, OpenSpec Scaffold
# ---------------------------------------------------------------------------

def _detect_package_manager(worktree_path: str) -> str | None:
    """Detect which package manager to use from lock files."""
    wt = Path(worktree_path)
    if (wt / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (wt / "yarn.lock").exists():
        return "yarn"
    if (wt / "package-lock.json").exists():
        return "npm"
    if (wt / "package.json").exists():
        return "npm"
    return None


def _install_deps(worktree_path: str, *, dry_run: bool = False) -> bool:
    """Install project dependencies in the worktree."""
    if dry_run:
        return True

    pm = _detect_package_manager(worktree_path)
    if not pm:
        return False

    install_cmds = {
        "pnpm": ["pnpm", "install", "--frozen-lockfile"],
        "yarn": ["yarn", "install", "--frozen-lockfile"],
        "npm": ["npm", "ci"],
    }
    cmd = install_cmds.get(pm)
    if not cmd:
        return False

    rc, _, _ = _run_cmd(cmd, cwd=worktree_path, timeout=120)
    return rc == 0


def create_worktree(
    repo_root: str,
    source_id_lower: str,
    *,
    dry_run: bool = False,
) -> WorktreeInfo:
    """Create a feature branch and git worktree for isolated development."""
    info = WorktreeInfo()
    info.repo_root = repo_root
    info.branch = f"dark-factory/{source_id_lower}"
    info.change_id = f"dark-factory-{source_id_lower}"

    basename_result = Path(repo_root).resolve().name
    info.worktree_path = str(
        Path(repo_root).parent / f"{basename_result}-df-{source_id_lower}"
    )

    if dry_run:
        return info

    _run_git(
        ["worktree", "add", "-b", info.branch, info.worktree_path, "main"],
        cwd=repo_root,
    )

    return info


def _ensure_gitignore(repo_root: str) -> None:
    """Ensure .dark-factory/ is gitignored in the main repo."""
    gitignore_path = Path(repo_root) / ".gitignore"
    marker = ".dark-factory/"

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if marker in content:
            return

    with gitignore_path.open("a") as f:
        f.write(f"\n{marker}\n")


def _validate_openspec(
    change_id: str, worktree_path: str, *, dry_run: bool = False
) -> bool:
    """Validate the openspec change with ``openspec validate``."""
    if dry_run:
        return True

    rc, _, _ = _run_cmd(
        ["openspec", "validate", change_id, "--strict"],
        cwd=worktree_path,
        timeout=30,
    )
    return rc == 0


async def run_phase_3(
    state: PipelineState,
    source_id_lower: str,
    summary: str,
    description: str,
    acceptance_criteria: list[str],
    external_ref: str,
    exploration_output: str = "",
    *,
    dry_run: bool = False,
) -> ScaffoldResult:
    """Phase 3: create branch/worktree, install deps, generate openspec scaffold.

    Uses an SDK call (sonnet, max_turns=5) to generate the openspec change
    files (proposal.md, spec.md, tasks.md) from the ticket fields and
    exploration context.
    """
    result = ScaffoldResult()

    # Create worktree
    worktree_info = create_worktree(
        state.repo_root, source_id_lower, dry_run=dry_run
    )
    result.worktree = worktree_info
    state.worktree_path = worktree_info.worktree_path
    state.branch = worktree_info.branch

    # Install dependencies
    result.deps_installed = _install_deps(
        worktree_info.worktree_path, dry_run=dry_run
    )

    # Ensure .dark-factory/ is gitignored
    if not dry_run:
        _ensure_gitignore(state.repo_root)

    # Create openspec directory structure
    change_dir = (
        Path(worktree_info.worktree_path)
        / "openspec"
        / "changes"
        / worktree_info.change_id
    )
    specs_dir = change_dir / "specs" / "main"

    if not dry_run:
        specs_dir.mkdir(parents=True, exist_ok=True)

    # Generate openspec files via SDK
    ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(derived from description)"

    scaffold_prompt = (
        f"Generate OpenSpec change files for this feature.\n\n"
        f"## Source\n"
        f"External ref: {external_ref}\n"
        f"Summary: {summary}\n\n"
        f"## Description\n{description}\n\n"
        f"## Acceptance Criteria\n{ac_text}\n\n"
        f"## Exploration Context\n{exploration_output[:3000] if exploration_output else '(none)'}\n\n"
        f"Generate THREE files. Output each with a header line like "
        f"'=== FILE: <filename> ===' followed by the content.\n\n"
        f"1. **proposal.md**: Why this change, what changes, impact.\n"
        f"2. **spec.md**: Requirements in OpenSpec delta format with "
        f"GIVEN/WHEN/THEN Gherkin scenarios for each acceptance criterion. "
        f"Include error/edge case scenarios.\n"
        f"3. **tasks.md**: Ordered implementation checklist. Each task maps "
        f"to a beads issue. Classify each task's independence:\n"
        f"   - `[P]` = parallel/independent — can run at the same time as other [P] tasks\n"
        f"   - `[depends: N]` = sequential — must run after task N completes\n"
        f"   - `[depends: N, M]` = sequential — must run after tasks N and M both complete\n"
        f"   Tasks WITHOUT markers default to sequential (each depends on the previous).\n\n"
        f"   **Examples:**\n"
        f"   ```\n"
        f"   1. [P] Add user validation endpoint\n"
        f"   2. [P] Add email notification service\n"
        f"   3. [depends: 1, 2] Wire validation into notification flow\n"
        f"   4. [P] Update API documentation\n"
        f"   ```\n"
        f"   In this example, tasks 1, 2, and 4 run concurrently (wave 0), "
        f"task 3 runs after both 1 and 2 finish (wave 1).\n\n"
        f"   **Guidelines for classifying tasks:**\n"
        f"   - Mark `[P]` if the task touches different files/modules than other tasks\n"
        f"   - Mark `[depends: N]` if the task builds on code written by task N\n"
        f"   - When in doubt, use `[depends: N]` — false sequential is safe, false parallel causes merge conflicts\n\n"
        f"Write each file directly to disk using the Write tool:\n"
        f"- {change_dir}/proposal.md\n"
        f"- {specs_dir}/spec.md\n"
        f"- {change_dir}/tasks.md\n\n"
        f"Write all three files. Do not ask for confirmation."
    )

    from .agents import _sdk_query, MODEL_SONNET

    messages, cost, _turns = await _sdk_query(
        scaffold_prompt,
        model=MODEL_SONNET,
        max_turns=5,
        allowed_tools=[],
    )
    result.scaffold_cost_usd = cost

    # The SDK model may write files directly via tool use, or return text output.
    # Check disk first; only fall back to text parsing if files don't exist.
    if not dry_run:
        _written_by_model = {
            "proposal.md": change_dir / "proposal.md",
            "spec.md": specs_dir / "spec.md",
            "tasks.md": change_dir / "tasks.md",
        }
        needs_parse = any(
            not p.exists() or p.stat().st_size == 0
            for p in _written_by_model.values()
        )

        if needs_parse:
            combined = "\n".join(messages)
            files = _parse_scaffold_output(combined)
            for filename, content in files.items():
                if filename == "proposal.md":
                    (change_dir / filename).write_text(content)
                elif filename == "spec.md":
                    (specs_dir / filename).write_text(content)
                elif filename == "tasks.md":
                    (change_dir / filename).write_text(content)

    # Validate openspec
    result.openspec_validated = _validate_openspec(
        worktree_info.change_id,
        worktree_info.worktree_path,
        dry_run=dry_run,
    )

    return result


def _parse_scaffold_output(text: str) -> dict[str, str]:
    """Parse the SDK output to extract individual file contents.

    Expects '=== FILE: <name> ===' delimiters between files.
    Falls back to heuristic splitting if delimiters are missing.
    """
    import re

    files: dict[str, str] = {}
    pattern = re.compile(r"===\s*FILE:\s*([\w./-]+)\s*===\s*\n")
    parts = pattern.split(text)

    if len(parts) >= 3:
        # parts: [preamble, name1, content1, name2, content2, ...]
        for i in range(1, len(parts), 2):
            name = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            # Normalize filename
            basename = Path(name).name
            if basename in ("proposal.md", "spec.md", "tasks.md"):
                files[basename] = content
    else:
        # Heuristic: look for markdown headers that indicate file boundaries
        sections = re.split(r"(?m)^#+\s*(?:proposal|spec|tasks)\.md\s*$", text, flags=re.IGNORECASE)
        filenames = ["proposal.md", "spec.md", "tasks.md"]
        for i, name in enumerate(filenames):
            idx = i + 1  # skip preamble
            if idx < len(sections):
                files[name] = sections[idx].strip()

    # Ensure all three files exist with at least placeholder content
    for name in ("proposal.md", "spec.md", "tasks.md"):
        if name not in files:
            files[name] = f"# {name}\n\n(Generated by Dark Factory)\n"

    return files


# ---------------------------------------------------------------------------
# Phase 4: Plan Review Gate
# ---------------------------------------------------------------------------

async def run_phase_4(
    worktree_path: str,
    change_id: str,
    external_ref: str,
    summary: str,
    acceptance_criteria: list[str],
    exploration_output: str = "",
    *,
    dry_run: bool = False,
) -> PlanReviewResult:
    """Phase 4: spawn a review agent to check the plan.

    Uses sonnet (max_turns=10, read-only tools) to review proposal.md,
    spec.md, and tasks.md for completeness, feasibility, missed edge
    cases, and scope creep.

    If NEEDS_WORK, the caller incorporates feedback. We do not re-run
    the review -- proceed to human checkpoint with fixes noted.
    """
    result = PlanReviewResult()

    # Read the openspec files
    change_dir = Path(worktree_path) / "openspec" / "changes" / change_id
    proposal = _read_safe(change_dir / "proposal.md")
    spec = _read_safe(change_dir / "specs" / "main" / "spec.md")
    tasks = _read_safe(change_dir / "tasks.md")

    ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"

    review_prompt = (
        f"Review the following development plan for completeness, feasibility, "
        f"missed edge cases, and scope creep.\n\n"
        f"## Source: {external_ref}\n"
        f"{summary}\n\n"
        f"## Acceptance Criteria\n{ac_text}\n\n"
        f"## Proposal\n{proposal}\n\n"
        f"## Spec\n{spec}\n\n"
        f"## Tasks\n{tasks}\n\n"
        f"## Codebase Context\n{exploration_output[:2000] if exploration_output else '(none)'}\n\n"
        f"Review criteria:\n"
        f"1. Are ALL acceptance criteria covered by Gherkin scenarios?\n"
        f"2. Is the plan feasible given the codebase structure?\n"
        f"3. Are there edge cases the spec missed?\n"
        f"4. Does the plan stay within scope (no scope creep)?\n\n"
        f"Return your verdict as PASS or NEEDS_WORK, followed by a structured "
        f"list of findings with categories: coverage, feasibility, edge_case, scope_creep."
    )

    from .agents import call_review

    review_output, review_cost, _review_turns = await call_review(
        review_prompt,
        worktree_path=worktree_path,
        system_prompt=(
            "You are a plan reviewer. Evaluate the development plan against "
            "the acceptance criteria. Be thorough but pragmatic -- only flag "
            "issues that would materially affect the implementation."
        ),
        dry_run=dry_run,
    )
    result.review_output = review_output
    result.review_cost_usd = review_cost

    # Parse verdict
    if "NEEDS_WORK" in review_output.upper():
        result.verdict = "NEEDS_WORK"
    else:
        result.verdict = "PASS"

    # Commit openspec files (if not dry run)
    if not dry_run:
        try:
            _run_git(
                ["add", f"openspec/changes/{change_id}/"],
                cwd=worktree_path,
            )
            # Also add .gitignore if it was modified
            gitignore = Path(worktree_path) / ".gitignore"
            if gitignore.exists():
                _run_git(["add", ".gitignore"], cwd=worktree_path)

            source_id = change_id.replace("dark-factory-", "")
            _run_git(
                ["commit", "-m", f"checkpoint(openspec): add spec for {source_id}"],
                cwd=worktree_path,
            )
        except RuntimeError:
            pass  # commit may fail if nothing to commit

    return result


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string if missing."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
