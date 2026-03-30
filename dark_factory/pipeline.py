"""Pipeline orchestration: phase runner with timing and state persistence.

The orchestrator owns all phase transitions.  The LLM is never consulted
about which phase to run next.
"""

from __future__ import annotations

import json as _json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .state import PipelineError, PipelineState
from .verify import detect_test_command


# Phase name lookup (duplicated from orchestrator to avoid circular import)
_PHASE_NAMES: dict[float, str] = {
    0: "Tool Discovery",
    1: "Source Ingestion",
    1.5: "Input Quality Gate",
    2: "Codebase Exploration",
    3: "Scaffold & OpenSpec",
    4: "Plan Review Gate",
    5: "Human Checkpoint",
    6: "Issue Creation",
    6.5: "Test Generation",
    6.75: "Sprint Contracts",
    7: "Implementation",
    8: "Test & Dep Audit",
    9: "Implementation Review",
    10: "Local Dev Verification",
    11: "PR Creation",
}


def _log_phase_event(
    state: PipelineState,
    phase: float,
    outcome: str,
    *,
    duration_ms: int | None = None,
) -> None:
    """Append a structured JSONL event for phase transitions.

    Events are written to `.dark-factory/<key>.events.jsonl` for
    post-run observability.
    """
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase_number": phase,
        "phase_name": _PHASE_NAMES.get(phase, f"Phase {phase}"),
        "outcome": outcome,
    }
    if duration_ms is not None:
        event["duration_ms"] = duration_ms

    try:
        events_dir = Path(state.repo_root) / ".dark-factory"
        events_dir.mkdir(parents=True, exist_ok=True)
        events_path = events_dir / f"{state.source.id}.events.jsonl"
        with events_path.open("a") as f:
            f.write(_json.dumps(event) + "\n")
    except OSError:
        pass  # best-effort logging


def _log_task_event(
    state: PipelineState,
    event_type: str,
    *,
    task_id: str = "",
    task_title: str = "",
    wave: int | None = None,
    success: bool | None = None,
    duration_ms: int | None = None,
) -> None:
    """Append a structured JSONL event for task-level transitions.

    Event types: task_start, task_complete, wave_start, wave_complete, task_skipped
    """
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
    }
    if task_id:
        event["task_id"] = task_id
    if task_title:
        event["task_title"] = task_title
    if wave is not None:
        event["wave"] = wave
    if success is not None:
        event["success"] = success
    if duration_ms is not None:
        event["duration_ms"] = duration_ms

    try:
        events_dir = Path(state.repo_root) / ".dark-factory"
        events_dir.mkdir(parents=True, exist_ok=True)
        events_path = events_dir / f"{state.source.id}.events.jsonl"
        with events_path.open("a") as f:
            f.write(_json.dumps(event) + "\n")
    except OSError:
        pass


async def run_phase(
    state: PipelineState,
    phase: float,
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute a phase function with timing, state tracking, and persistence.

    On success: records timing, appends to completed_phases, advances
    current_phase, and saves state.

    On failure: saves state (preserving progress for --resume) and raises
    PipelineError.
    """
    _log_phase_event(state, phase, "started")
    state.pipeline_status = "running"
    start = time.monotonic()
    try:
        result = await fn(*args, **kwargs)
        elapsed = time.monotonic() - start

        state.phase_timings[str(phase)] = round(elapsed, 3)
        state.completed_phases.append(phase)
        # Sub-phase routing: 1 → 1.5, 1.5 → 2, 6 → 6.5, 6.5 → 7
        if phase == 1:
            state.current_phase = 1.5
        elif phase == 1.5:
            state.current_phase = 2
        elif phase == 6:
            state.current_phase = 6.5
        elif phase == 6.5:
            state.current_phase = 6.75
        elif phase == 6.75:
            state.current_phase = 7
        else:
            state.current_phase = int(phase) + 1
        state.save()
        state.phase7_progress = None  # clear intra-phase detail
        _log_phase_event(
            state, phase, "completed", duration_ms=round(elapsed * 1000),
        )

        return result

    except Exception as exc:
        elapsed = time.monotonic() - start
        state.phase_timings[str(phase)] = round(elapsed, 3)
        # TimeoutError has no message — provide a meaningful one
        msg = str(exc) or f"{type(exc).__name__} after {elapsed:.0f}s"
        state.error = msg
        state.save()  # preserve state for --resume
        state.pipeline_status = "failed"
        _log_phase_event(
            state, phase, "failed", duration_ms=round(elapsed * 1000),
        )
        raise PipelineError(phase, msg) from exc


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1.5: Input Quality Gate — DoR + INVEST assessment
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ReadinessReport:
    """Outcome of Phase 1.5: input quality assessment."""

    score: int = 100
    gaps: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    dor_checks: dict[str, bool] = field(default_factory=dict)
    invest_checks: dict[str, bool] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.score >= 80:
            return "ready"
        elif self.score >= 50:
            return "gaps_found"
        return "not_ready"


def _quick_input_check(ticket: "TicketFields") -> list[str]:
    """Short-circuit obviously broken input before calling Sonnet."""
    issues: list[str] = []
    if not ticket.summary.strip():
        issues.append("Summary is empty")
    elif len(ticket.summary.strip()) < 10:
        issues.append("Summary too brief")
    if not ticket.acceptance_criteria:
        issues.append("No acceptance criteria")
    return issues


async def run_phase_1_5(
    state: PipelineState,
    ticket: "TicketFields",
    *,
    dry_run: bool = False,
) -> ReadinessReport:
    """Phase 1.5: evaluate ticket against DoR and INVEST criteria.

    Runs a deterministic pre-check first. If the ticket is obviously broken,
    returns score=0 without an SDK call. Otherwise calls Sonnet to assess
    semantic quality and returns a ReadinessReport.
    """
    import json as _json

    from .agents import call_quality_gate
    from .ingest import TicketFields  # noqa: F811 — late import to avoid circular

    # Deterministic pre-check
    quick_issues = _quick_input_check(ticket)
    if quick_issues:
        return ReadinessReport(score=0, gaps=quick_issues)

    if dry_run:
        return ReadinessReport(score=100)

    # Build the quality-gate prompt
    ac_list = "\n".join(f"- {ac}" for ac in ticket.acceptance_criteria)
    prompt = (
        "Evaluate this ticket against Definition of Ready and INVEST criteria.\n\n"
        "## Ticket\n"
        f"Summary: {ticket.summary}\n"
        f"Description: {ticket.description}\n"
        f"Acceptance Criteria:\n{ac_list}\n\n"
        "## Evaluate Against\n"
        "### Definition of Ready\n"
        "1. Business value articulated (As a... I want... So that...)\n"
        "2. Acceptance criteria describe all features of the story\n"
        "3. No external dependencies prevent completion\n"
        "4. Story scope is realistic\n\n"
        "### INVEST Criteria\n"
        "1. Independent — no unresolved external dependencies\n"
        "2. Valuable — clear benefit stated\n"
        "3. Small — not an epic disguised as a story\n"
        "4. Testable — AC are concrete and verifiable\n\n"
        "## Output Format\n"
        "Return a JSON object:\n"
        "{\n"
        '  "score": <0-100>,\n'
        '  "dor_checks": {"business_value": true/false, "ac_complete": true/false, '
        '"no_blockers": true/false, "realistic_scope": true/false},\n'
        '  "invest_checks": {"independent": true/false, "valuable": true/false, '
        '"small": true/false, "testable": true/false},\n'
        '  "gaps": ["list of issues found"],\n'
        '  "suggestions": ["list of improvements"]\n'
        "}\n"
    )

    output, _cost, _turns = await call_quality_gate(prompt, dry_run=dry_run)

    # Parse JSON from the LLM response
    return _parse_readiness_response(output)


def _parse_readiness_response(text: str) -> ReadinessReport:
    """Extract a ReadinessReport from the quality-gate LLM response."""
    import json as _json
    import re

    # Try to find a JSON block (fenced or bare)
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    raw = json_match.group(1) if json_match else text

    # Also try bare JSON object
    if not json_match:
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if obj_match:
            raw = obj_match.group(0)

    try:
        data = _json.loads(raw)
        return ReadinessReport(
            score=int(data.get("score", 0)),
            gaps=data.get("gaps", []),
            suggestions=data.get("suggestions", []),
            dor_checks=data.get("dor_checks", {}),
            invest_checks=data.get("invest_checks", {}),
        )
    except (_json.JSONDecodeError, ValueError, TypeError):
        # LLM returned unparseable output — conservative fallback
        return ReadinessReport(
            score=50,
            gaps=["Could not parse quality gate response"],
            suggestions=["Re-run the quality gate or review manually"],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6.5: Test Generation — spec-to-test before implementation
# ═══════════════════════════════════════════════════════════════════════════════

# Test directory detection heuristic (mirrors verify.py fallback patterns)
_TEST_DIR_MARKERS: dict[str, str] = {
    "conftest.py": "tests",
    "pytest.ini": "tests",
    "tests": "tests",
    "test": "test",
    "__tests__": "__tests__",
    "spec": "spec",
}


def _detect_test_dir(worktree_path: str) -> str:
    """Detect the project's test directory from conventions."""
    from pathlib import Path

    wt = Path(worktree_path)

    # Check for existing test directories
    for marker, test_dir in _TEST_DIR_MARKERS.items():
        if (wt / marker).exists():
            return test_dir

    # Default to 'tests' for Python, '__tests__' for JS
    if (wt / "pyproject.toml").exists() or (wt / "setup.py").exists():
        return "tests"
    if (wt / "package.json").exists():
        return "__tests__"

    return "tests"


@dataclass
class Phase6_5Result:
    """Outcome of Phase 6.5: test generation."""

    visible_test_paths: list[str] = field(default_factory=list)
    holdout_test_paths: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


async def run_phase_6_5(
    state: PipelineState,
    worktree_path: str,
    spec_texts: list[str],
    *,
    dry_run: bool = False,
) -> Phase6_5Result:
    """Phase 6.5: generate visible and hold-out tests from specs.

    Uses Sonnet (read-only tools) to read specs and produce two test sets.
    The implementing agent (Phase 7) sees visible tests but not hold-out tests.
    """
    from pathlib import Path

    from .agents import call_test_gen

    result = Phase6_5Result()

    if not spec_texts:
        return result

    if dry_run:
        return result

    # Build the test generation prompt — role goes in system_prompt to avoid
    # prompt-injection detection when running without --bare mode.
    combined_specs = "\n\n---\n\n".join(spec_texts)

    system_prompt = (
        "You are a test generation agent for a software project. "
        "Your job is to read specifications and generate test code that "
        "validates the requirements. Follow the project's testing conventions."
    )

    prompt = (
        "Read the following spec and generate test code that validates "
        "the requirements.\n\n"
        "## Specs\n"
        f"{combined_specs}\n\n"
        "## Instructions\n"
        "1. Generate tests for each Gherkin scenario in the specs\n"
        "2. Split your output into TWO clearly marked sections:\n\n"
        "### VISIBLE_TESTS_START\n"
        "Tests for happy-path and core error scenarios. These will be given "
        "to the implementation agent as TDD targets.\n"
        "### VISIBLE_TESTS_END\n\n"
        "### HOLDOUT_TESTS_START\n"
        "Tests for edge cases, boundary conditions, and secondary error paths. "
        "These will be hidden from the implementation agent.\n"
        "### HOLDOUT_TESTS_END\n\n"
        "3. Follow the project's testing conventions (framework, naming)\n"
        "4. Each test should be independent and self-contained\n"
        "5. If only 1 scenario exists, put the test in VISIBLE only\n"
    )

    output, cost, _turns = await call_test_gen(
        prompt,
        worktree_path=worktree_path,
        system_prompt=system_prompt,
        dry_run=dry_run,
    )
    result.cost_usd = cost

    # Parse visible and hold-out test content from output
    visible_content = _extract_section(output, "VISIBLE_TESTS_START", "VISIBLE_TESTS_END")
    holdout_content = _extract_section(output, "HOLDOUT_TESTS_START", "HOLDOUT_TESTS_END")

    if not visible_content and not holdout_content:
        raise PipelineError(
            6.5,
            "Test generation produced no test content from non-empty spec. "
            f"Agent output (first 500 chars): {output[:500]}"
        )

    # Single-scenario guard: when spec has only 1 scenario, all tests
    # must be visible (no holdout split possible). Merge any holdout
    # content into visible to enforce deterministically, since the LLM
    # prompt alone ("put the test in VISIBLE only") is not reliable.
    if len(spec_texts) == 1 and holdout_content:
        if visible_content:
            visible_content = visible_content + "\n\n" + holdout_content
        else:
            visible_content = holdout_content
        holdout_content = ""

    # Write test files to worktree
    test_dir = _detect_test_dir(worktree_path)
    wt = Path(worktree_path)
    test_dir_path = wt / test_dir
    test_dir_path.mkdir(parents=True, exist_ok=True)

    source_id = state.source.id

    if visible_content:
        visible_path = test_dir_path / f"visible_tests_{source_id}.py"
        visible_path.write_text(visible_content)
        if not visible_path.exists() or visible_path.stat().st_size == 0:
            raise PipelineError(
                6.5, f"Failed to write visible test file: {visible_path}"
            )
        result.visible_test_paths.append(str(visible_path))

    if holdout_content:
        holdout_path = test_dir_path / f"holdout_tests_{source_id}.py"
        holdout_path.write_text(holdout_content)
        if not holdout_path.exists() or holdout_path.stat().st_size == 0:
            raise PipelineError(
                6.5, f"Failed to write holdout test file: {holdout_path}"
            )
        result.holdout_test_paths.append(str(holdout_path))

    # Persist to state
    state.visible_test_paths = result.visible_test_paths
    state.holdout_test_paths = result.holdout_test_paths

    return result


def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
    """Extract content between markers from agent output."""
    import re

    pattern = rf"###\s*{start_marker}\s*\n(.*?)###\s*{end_marker}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6.75: Sprint Contracts — pre-execution agreement
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SprintContract:
    """A contract for a single task: what to build, how to verify."""

    task_id: str
    task_title: str
    approach: str = ""
    verification: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class Phase6_75Result:
    """Outcome of Phase 6.75: sprint contract negotiation."""

    contracts: list[SprintContract] = field(default_factory=list)
    cost_usd: float = 0.0
    validated: bool = False


async def run_phase_6_75(
    state: PipelineState,
    issues: list[dict[str, Any]],
    worktree_path: str,
    spec_text: str = "",
    *,
    dry_run: bool = False,
) -> Phase6_75Result:
    """Phase 6.75: generate and validate sprint contracts before implementation.

    For each non-epic issue, asks Sonnet to produce a contract describing what
    will be built and how success will be verified. Then validates all contracts
    against the spec.
    """
    import json as _json

    from .agents import call_review

    result = Phase6_75Result()
    task_issues = [i for i in issues if i.get("type", "task") != "epic"]

    if not task_issues or dry_run:
        return result

    # Generate contracts
    task_list = "\n".join(
        f"- {i.get('id', '?')}: {i.get('title', '')}" for i in task_issues
    )
    gen_prompt = (
        "For each task below, produce a sprint contract describing:\n"
        "1. **approach**: what will be built (implementation strategy)\n"
        "2. **verification**: how success will be verified (test strategy)\n"
        "3. **acceptance_criteria**: list of concrete, testable criteria\n\n"
        f"## Spec\n{spec_text or '(no spec provided)'}\n\n"
        f"## Tasks\n{task_list}\n\n"
        "Return a JSON array of objects:\n"
        "```json\n"
        '[{"task_id": "...", "approach": "...", "verification": "...", '
        '"acceptance_criteria": ["..."]}]\n'
        "```\n"
    )

    gen_output, gen_cost, _ = await call_review(
        gen_prompt, worktree_path=worktree_path, dry_run=dry_run,
    )
    result.cost_usd += gen_cost

    # Parse contracts from response
    contracts = _parse_contracts(gen_output, task_issues)
    result.contracts = contracts

    # Validate contracts against spec
    if contracts and spec_text:
        contract_summary = "\n".join(
            f"- {c.task_id}: approach={c.approach[:100]}, "
            f"criteria={len(c.acceptance_criteria)}"
            for c in contracts
        )
        val_prompt = (
            "Validate these sprint contracts against the spec. "
            "Check for: missing requirements, contradictions, untestable criteria.\n\n"
            f"## Spec\n{spec_text[:2000]}\n\n"
            f"## Contracts\n{contract_summary}\n\n"
            "Return VALIDATED if contracts are sufficient, or list issues."
        )
        val_output, val_cost, _ = await call_review(
            val_prompt, worktree_path=worktree_path, dry_run=dry_run,
        )
        result.cost_usd += val_cost
        result.validated = "VALIDATED" in val_output.upper()

    return result


def _parse_contracts(
    text: str,
    task_issues: list[dict[str, Any]],
) -> list[SprintContract]:
    """Extract SprintContract objects from the LLM response."""
    import json as _json
    import re

    # Try to find JSON array in response
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    raw = json_match.group(1) if json_match else text

    if not json_match:
        arr_match = re.search(r"\[.*\]", text, re.DOTALL)
        if arr_match:
            raw = arr_match.group(0)

    try:
        data = _json.loads(raw)
        if not isinstance(data, list):
            data = [data]
    except (_json.JSONDecodeError, ValueError):
        # Fallback: create empty contracts for each task
        return [
            SprintContract(
                task_id=i.get("id", "?"),
                task_title=i.get("title", ""),
            )
            for i in task_issues
        ]

    contracts = []
    for item in data:
        contracts.append(SprintContract(
            task_id=item.get("task_id", ""),
            task_title=next(
                (i.get("title", "") for i in task_issues
                 if i.get("id") == item.get("task_id")),
                "",
            ),
            approach=item.get("approach", ""),
            verification=item.get("verification", ""),
            acceptance_criteria=item.get("acceptance_criteria", []),
        ))

    return contracts


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7: Implementation — implement loop
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ImplementationResult:
    """Outcome of Phase 7 for a single issue."""

    issue_id: str
    success: bool
    output: str = ""
    cost_usd: float = 0.0


@dataclass
class MergeConflict:
    """A merge conflict from parallel execution."""

    issue_id: str
    branch_name: str
    status: str = "needs-manual-merge"


@dataclass
class Phase7Result:
    """Aggregate outcome of Phase 7."""

    results: list[ImplementationResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    merge_conflicts: list[MergeConflict] = field(default_factory=list)


def _is_off_rails(messages: list[str]) -> bool:
    """Heuristic guard: detect when an implementation agent goes off-rails.

    Triggers interrupt() if the agent appears stuck in a loop or is doing
    something clearly outside scope.
    """
    if len(messages) < 10:
        return False

    # Repeated identical messages suggest a stuck loop
    recent = messages[-5:]
    if len(set(recent)) == 1:
        return True

    # Excessive message count without progress
    if len(messages) > 100:
        return True

    return False


def _build_phase7_prompt(
    worktree_path: str,
    issue_id: str,
    issue_title: str,
    sprint_contract: dict[str, Any] | None = None,
) -> str:
    """Build the implementation prompt for a single Phase 7 issue."""
    prompt = (
        f"You are implementing an issue in a codebase.\n\n"
        f"## Working Directory\n"
        f"You are working in a git worktree at: {worktree_path}\n\n"
        f"## Your Issue\n"
        f"ID: {issue_id}\n"
        f"Title: {issue_title}\n\n"
    )

    if sprint_contract:
        prompt += (
            f"## Sprint Contract (agreed approach)\n"
            f"Approach: {sprint_contract.get('approach', 'N/A')}\n"
            f"Verification: {sprint_contract.get('verification', 'N/A')}\n"
        )
        ac = sprint_contract.get("acceptance_criteria", [])
        if ac:
            prompt += "Acceptance Criteria:\n"
            for criterion in ac:
                prompt += f"- {criterion}\n"
        prompt += "\n"

    prompt += (
        f"## Instructions\n"
        f"1. Read the repo's CLAUDE.md for conventions and test commands\n"
        f"2. Explore the codebase to understand relevant code and patterns\n"
        f"3. Implement the changes described in your issue\n"
        f"4. Write or update tests to cover the changes\n"
        f"5. Follow existing code patterns and conventions\n"
        f"6. Self-review checklist before committing:\n"
        f"   - Run `git diff --stat` — verify only expected files changed\n"
        f"   - grep for debug artifacts (console.log, print(), TODO, FIXME, debugger)\n"
        f"   - Confirm test files exist for new/modified source files\n"
        f"   - Run the project's lint command, fix remaining issues\n"
        f"   - Remove any commented-out code you added\n"
        f"7. Create a checkpoint commit:\n"
        f"   checkpoint(<scope>): {issue_title}\n"
        f"   Implements {issue_id}\n"
        f"8. After completing each file change, run the project's lint command if available.\n"
        f"   Fix any lint errors before moving to the next file.\n\n"
        f"Do NOT modify files unrelated to your issue.\n"
        f"Do NOT over-engineer — implement exactly what the issue asks for."
    )
    return prompt


def _run_targeted_tests(
    worktree_path: str,
    test_command: str | None = None,
    *,
    dry_run: bool = False,
) -> str:
    """Run targeted tests after each task. Returns test output or empty string."""
    if dry_run or not test_command:
        return ""

    try:
        result = subprocess.run(
            test_command,
            shell=True,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (result.stdout + "\n" + result.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def merge_parallel_branch(
    main_worktree: str,
    branch_name: str,
) -> bool:
    """Merge a parallel branch into the main worktree.

    Returns True if merge succeeded, False if conflict.
    """
    try:
        result = subprocess.run(
            ["git", "merge", "--no-edit", branch_name],
            cwd=main_worktree,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _abort_merge(worktree_path: str) -> None:
    """Abort a failed merge."""
    try:
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


async def _implement_single_task(
    state: PipelineState,
    issue: dict[str, Any],
    worktree_path: str,
    system_prompt: str | None,
    *,
    dry_run: bool = False,
) -> ImplementationResult:
    """Implement a single issue -- extracted from the Phase 7 loop."""
    from .agents import call_implement

    issue_id = issue.get("id", "unknown")
    issue_title = issue.get("title", "")

    _log_task_event(state, "task_start", task_id=issue_id, task_title=issue_title)

    # Find sprint contract for this task (if available)
    contract = next(
        (c for c in state.sprint_contracts if c.get("task_id") == issue_id),
        None,
    )

    prompt = _build_phase7_prompt(
        worktree_path=worktree_path,
        issue_id=issue_id,
        issue_title=issue_title,
        sprint_contract=contract,
    )

    if state.visible_test_paths:
        tdd_section = "\n\n## TDD Tests (make these pass)\n"
        tdd_section += (
            "The following tests were generated from the spec. "
            "Your implementation MUST make them pass.\n"
            "Do NOT modify these test files.\n\n"
        )
        from pathlib import Path

        for test_path in state.visible_test_paths:
            p = Path(test_path)
            if p.exists():
                tdd_section += f"### {p.name}\n```\n{p.read_text()}\n```\n\n"
        prompt += tdd_section

    impl_output, impl_cost, _num_turns = await call_implement(
        prompt,
        worktree_path=worktree_path,
        system_prompt=system_prompt,
        is_off_rails=_is_off_rails,
        dry_run=dry_run,
    )

    # Accumulate cost into pipeline state for observability
    state.total_cost_usd += impl_cost

    # Cost circuit breaker
    if (state.max_cost_usd is not None
            and state.total_cost_usd > state.max_cost_usd):
        import sys
        print(
            f"⚠️  Cost budget exceeded: ${state.total_cost_usd:.2f} > "
            f"${state.max_cost_usd:.2f}",
            file=sys.stderr,
        )
        state.save()
        raise PipelineError(
            7,
            f"Cost budget exceeded: ${state.total_cost_usd:.2f} > "
            f"${state.max_cost_usd:.2f}. Use --resume to continue.",
        )

    impl_result = ImplementationResult(
        issue_id=issue_id,
        success=True,
        output=impl_output,
        cost_usd=impl_cost,
    )

    test_cmd = detect_test_command(worktree_path)
    if test_cmd and not dry_run:
        test_output = _run_targeted_tests(
            worktree_path, test_cmd, dry_run=dry_run,
        )
        if test_output and "FAILED" in test_output.upper():
            impl_result.output += (
                f"\n\n⚠️ Targeted test warning:\n{test_output[-1000:]}"
            )

    _log_task_event(state, "task_complete", task_id=issue_id, success=impl_result.success)

    # Checkpoint completed task for partial resume
    if impl_result.success:
        state.phase7_completed_tasks.append(issue_id)
        state.save()

    return impl_result


async def _run_wave(
    state: PipelineState,
    wave_issues: list[dict[str, Any]],
    main_worktree: str,
    system_prompt: str | None,
    *,
    dry_run: bool = False,
) -> tuple[list[ImplementationResult], list[MergeConflict]]:
    """Execute a wave of tasks, respecting max_parallel.

    Single-task waves use the main worktree directly.
    Multi-task waves use parallel worktrees and merge after.

    Returns (results, merge_conflicts).
    """
    import asyncio

    from .worktree import create_parallel_worktree, remove_parallel_worktree

    if len(wave_issues) == 1:
        result = await _implement_single_task(
            state, wave_issues[0], main_worktree, system_prompt, dry_run=dry_run,
        )
        return [result], []

    # Multi-task wave -- batch by max_parallel
    all_results: list[ImplementationResult] = []
    all_conflicts: list[MergeConflict] = []
    max_p = state.max_parallel

    for batch_start in range(0, len(wave_issues), max_p):
        batch = wave_issues[batch_start:batch_start + max_p]

        # Create worktrees for each task in the batch
        worktrees: list[tuple[dict[str, Any], str, str]] = []  # (issue, wt_path, branch)
        for issue in batch:
            issue_id = issue.get("id", "unknown")
            pwt = create_parallel_worktree(
                state.repo_root, issue_id, dry_run=dry_run,
            )
            worktrees.append((issue, pwt.worktree_path, pwt.branch_name))

        # Run all tasks in the batch concurrently
        coros = [
            _implement_single_task(
                state, issue, wt_path, system_prompt, dry_run=dry_run,
            )
            for issue, wt_path, _branch in worktrees
        ]
        batch_results = await asyncio.gather(*coros, return_exceptions=True)

        # Process results and cleanup worktrees
        for i, raw_result in enumerate(batch_results):
            issue, wt_path, branch = worktrees[i]
            issue_id = issue.get("id", "unknown")

            if isinstance(raw_result, BaseException):
                all_results.append(ImplementationResult(
                    issue_id=issue_id,
                    success=False,
                    output=str(raw_result),
                    cost_usd=0.0,
                ))
            else:
                all_results.append(raw_result)

            # Cleanup worktree (even on failure)
            if not dry_run:
                remove_parallel_worktree(wt_path, branch, state.repo_root)

        # Merge successful branches into main worktree
        for i, raw_result in enumerate(batch_results):
            if isinstance(raw_result, BaseException):
                continue
            if not raw_result.success:
                continue

            _, _, branch = worktrees[i]
            issue_id = worktrees[i][0].get("id", "unknown")

            if not dry_run:
                merged = merge_parallel_branch(main_worktree, branch)
                if not merged:
                    _abort_merge(main_worktree)
                    all_conflicts.append(MergeConflict(
                        issue_id=issue_id,
                        branch_name=branch,
                    ))

    return all_results, all_conflicts


def _has_dependency_markers(issues: list[dict[str, Any]]) -> bool:
    """Check if any issue title contains dependency markers."""
    for issue in issues:
        title = issue.get("title", "")
        if "[P]" in title or "[depends:" in title:
            return True
    return False


async def run_phase_7(
    state: PipelineState,
    issues: list[dict[str, Any]],
    worktree_path: str,
    system_prompt: str | None = None,
    *,
    dry_run: bool = False,
) -> Phase7Result:
    """Phase 7: for each issue, claim -> implement -> close.

    Supports parallel execution when tasks have dependency markers.
    Falls back to sequential for backward compatibility.
    """
    result = Phase7Result()

    # Filter out epics
    task_issues = [i for i in issues if i.get("type", "task") != "epic"]

    if not task_issues:
        return result

    # Skip tasks already completed on a previous run (partial resume)
    completed = set(state.phase7_completed_tasks)

    # Check for dependency markers
    if not _has_dependency_markers(task_issues):
        # Sequential fallback -- preserve existing behavior
        for issue in task_issues:
            if issue.get("id") in completed:
                _log_task_event(state, "task_skipped", task_id=issue.get("id", ""),
                               task_title=issue.get("title", ""))
                continue
            impl_result = await _implement_single_task(
                state, issue, worktree_path, system_prompt, dry_run=dry_run,
            )
            result.results.append(impl_result)
            result.total_cost_usd += impl_result.cost_usd
        return result

    # Wave-based parallel execution
    from .issues import TaskDAG, parse_tasks_md_with_deps

    # Build DAG from issue titles
    # Reconstruct a tasks.md-like text from issue titles to parse markers
    task_text = "\n".join(
        f"{i+1}. {issue.get('title', '')}" for i, issue in enumerate(task_issues)
    )
    parsed = parse_tasks_md_with_deps(task_text)

    dag = TaskDAG()
    for pt in parsed:
        dag.add_task(pt)

    # Map task indices to issue dicts
    index_to_issue = {i + 1: issue for i, issue in enumerate(task_issues)}

    # Resolve waves (as task indices)
    waves = dag.resolve_waves()

    # Track failed task indices for dependency skipping
    failed_indices: set[int] = set()

    for wave_idx, wave in enumerate(waves):
        # Skip tasks whose dependencies failed or already completed
        wave_issues = []
        for idx in wave:
            issue = index_to_issue[idx]
            if issue.get("id") in completed:
                _log_task_event(state, "task_skipped", task_id=issue.get("id", ""),
                               task_title=issue.get("title", ""))
                continue
            task_deps = dag._edges.get(idx, set())
            failed_deps = task_deps & failed_indices
            if failed_deps:
                issue = index_to_issue[idx]
                issue_id = issue.get("id", "unknown")
                _log_task_event(state, "task_skipped", task_id=issue_id,
                               task_title=issue.get("title", ""))
                result.results.append(ImplementationResult(
                    issue_id=issue_id,
                    success=False,
                    output=f"skipped_dependency_failed: dependencies {failed_deps} failed",
                    cost_usd=0.0,
                ))
                failed_indices.add(idx)
                continue
            wave_issues.append(index_to_issue[idx])

        if not wave_issues:
            continue

        state.phase7_progress = {
            "wave": wave_idx + 1,
            "total_waves": len(waves),
            "tasks_completed": len(result.results),
            "tasks_total": len(task_issues),
            "wave_task_ids": [iss.get("id", "?") for iss in wave_issues],
        }
        state.save()

        _log_task_event(state, "wave_start", wave=wave_idx + 1)

        wave_results, wave_conflicts = await _run_wave(
            state, wave_issues, worktree_path, system_prompt, dry_run=dry_run,
        )

        _log_task_event(state, "wave_complete", wave=wave_idx + 1)

        # Record results and track failures
        for wr in wave_results:
            result.results.append(wr)
            result.total_cost_usd += wr.cost_usd
            if not wr.success:
                for idx, issue in index_to_issue.items():
                    if issue.get("id") == wr.issue_id:
                        failed_indices.add(idx)
                        break

        result.merge_conflicts.extend(wave_conflicts)

        state.phase7_progress["tasks_completed"] = len(result.results)
        state.save()

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9: Implementation Review Gate
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ReviewResult:
    """Outcome of Phase 9."""

    verdict: str = "PASS"  # "PASS" or "NEEDS_FIX"
    review_output: str = ""
    fix_output: str = ""
    review_cost_usd: float = 0.0
    fix_cost_usd: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self.review_cost_usd + self.fix_cost_usd


MAX_REVIEW_FIX_CYCLES = 1

REVIEW_CALIBRATION = """\
## Calibration Examples

### Example 1: PASS — Correct code that looks suspicious
```python
# Calculating retry delay with exponential backoff
delay = min(base_delay * (2 ** attempt), max_delay)
time.sleep(delay + random.uniform(0, 0.1))  # jitter
```
Verdict: PASS
Reasoning: The jitter addition looks like a bug (adding to delay) but is intentional \
— it prevents thundering herd. The exponential backoff with cap is correct.

### Example 2: NEEDS_FIX — Subtle logic error in clean code
```python
def is_valid_range(start, end, items):
    \"\"\"Check if range [start, end] contains valid items.\"\"\"
    return all(item.is_valid() for item in items[start:end])
```
Verdict: NEEDS_FIX
Issues: Off-by-one error — Python slicing is [start:end) exclusive, but docstring \
says [start, end] inclusive. Should be items[start:end+1].

### Example 3: NEEDS_FIX — Security issue in working code
```python
def get_user_data(user_id, db):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return db.execute(query).fetchone()
```
Verdict: NEEDS_FIX
Issues: SQL injection vulnerability. Must use parameterized query: \
db.execute("SELECT * FROM users WHERE id = ?", (user_id,))

### Example 4: PASS — Intentional simplicity
```python
def retry(fn, max_attempts=3):
    for i in range(max_attempts):
        try:
            return fn()
        except Exception:
            if i == max_attempts - 1:
                raise
```
Verdict: PASS
Reasoning: No backoff or jitter, but appropriate for a simple retry helper. \
Adding complexity would be over-engineering for this use case.

### Example 5: NEEDS_FIX — Race condition
```python
def get_or_create_cache(key, factory):
    if key not in cache:
        cache[key] = factory()
    return cache[key]
```
Verdict: NEEDS_FIX
Issues: TOCTOU race condition in concurrent environments. Between the check and the \
set, another thread could create the same key. Use setdefault or a lock.
"""


async def run_phase_9(
    worktree_path: str,
    spec_text: str = "",
    *,
    dry_run: bool = False,
) -> ReviewResult:
    """Phase 9: git diff, SDK review (sonnet, read-only), fix cycle (opus).

    Max 1 review-fix cycle. Review agents use sonnet with read-only tools.
    Fix agents use opus with edit tools.
    """
    from .agents import call_fix, call_review

    result = ReviewResult()

    # Get diff for review
    if dry_run:
        diff_text = "[dry-run] no diff available"
    else:
        try:
            git_result = subprocess.run(
                ["git", "diff", "main...HEAD"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=30,
            )
            diff_text = git_result.stdout if git_result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            diff_text = ""

    if not diff_text and not dry_run:
        # No changes to review
        result.verdict = "PASS"
        result.review_output = "No changes detected on branch."
        return result

    # SDK review (sonnet, max_turns=10, read-only tools)
    review_prompt = (
        f"Review this implementation against its spec.\n\n"
        f"## Spec\n{spec_text or '(no spec provided)'}\n\n"
        f"## Changes (git diff)\n```\n{diff_text[-8000:]}\n```\n\n"
        f"{REVIEW_CALIBRATION}\n\n"
        f"Review for:\n"
        f"1. Spec compliance — does the code implement what the spec says?\n"
        f"2. Missing test coverage\n"
        f"3. Logic errors, security issues, hardcoded values\n"
        f"4. Over-engineering or scope creep\n"
        f"5. Debug artifacts (console.log, debugger, TODO/FIXME)\n\n"
        f"Return your verdict as either PASS or NEEDS_FIX, followed by "
        f"a list of issues (if any) with file:line references."
    )

    review_output, review_cost, _review_turns = await call_review(
        review_prompt,
        worktree_path=worktree_path,
        dry_run=dry_run,
    )
    result.review_output = review_output
    result.review_cost_usd = review_cost

    # Check verdict
    if "NEEDS_FIX" in review_output.upper():
        result.verdict = "NEEDS_FIX"

        # Fix cycle (opus, max_turns=10, edit tools) — max 1 cycle
        fix_prompt = (
            f"A code reviewer found issues with the implementation. "
            f"Fix the issues identified below.\n\n"
            f"## Review Feedback\n{review_output}\n\n"
            f"Fix the issues and commit with:\n"
            f"checkpoint(<scope>): address review feedback"
        )

        fix_output, fix_cost, _fix_turns = await call_fix(
            fix_prompt,
            worktree_path=worktree_path,
            system_prompt=(
                "You are a code-fix agent. Apply the review feedback precisely. "
                "Do not refactor beyond what the review asks for."
            ),
            dry_run=dry_run,
        )
        result.fix_output = fix_output
        result.fix_cost_usd = fix_cost
    else:
        result.verdict = "PASS"

    return result
