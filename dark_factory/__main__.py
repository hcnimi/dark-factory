"""Entry point for ``python3 -m dark_factory``.

Runs deterministic phases (0, 5, 6, 10) via JSON dispatch, and async
phases (3, 4, 7, 8, 9, 11) via the full orchestrator.  The ``run``
sub-command executes the complete pipeline end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from .checkpoint import (
    Decision,
    PlanSummary,
    parse_decision,
    parse_spec_requirements,
    parse_tasks,
    render_checkpoint,
)
from .cli import parse_args
from .explore import explore_codebase, prefetch_context
from .ingest import TicketFields, ingest_file, ingest_inline, ingest_jira
from .issues import create_issues, parse_tasks_md
from .scaffold import run_phase_3, run_phase_4
from .state import PipelineError, PipelineState
from .verify import detect_dev_command, render_verification_checklist


def _phase_0(argv: list[str]) -> dict:
    """Phase 0: argument parsing, tool checks, state initialization."""
    args = parse_args(argv)

    if args.missing_tools:
        return {
            "phase": 0,
            "status": "error",
            "error": f"Missing tools: {', '.join(args.missing_tools)}",
        }

    state = PipelineState(
        source=args.source,
        repo_root=".",
        dry_run=args.dry_run,
    )

    if args.resume:
        state_path = state._state_path()
        if state_path.exists():
            state = PipelineState.load(state_path)
            return {
                "phase": 0,
                "status": "resumed",
                "source": args.source.__dict__,
                "current_phase": state.current_phase,
                "completed_phases": state.completed_phases,
                "dry_run": args.dry_run,
            }

    return {
        "phase": 0,
        "status": "initialized",
        "source": args.source.__dict__,
        "dry_run": args.dry_run,
        "resume": args.resume,
    }


def _phase_5(argv: list[str]) -> dict:
    """Phase 5: render human checkpoint prompt.

    Expects JSON on stdin with plan details.
    """
    plan_data = json.loads(sys.stdin.read())

    spec_text = plan_data.get("spec_text", "")
    tasks_text = plan_data.get("tasks_text", "")
    dry_run = plan_data.get("dry_run", False)

    plan = PlanSummary(
        external_ref=plan_data["external_ref"],
        summary=plan_data["summary"],
        branch=plan_data["branch"],
        worktree_path=plan_data["worktree_path"],
        review_result=plan_data.get("review_result", "PASS"),
        spec_overview=plan_data.get("spec_overview", ""),
        requirements=parse_spec_requirements(spec_text) if spec_text else plan_data.get("requirements", []),
        tasks=parse_tasks(tasks_text) if tasks_text else plan_data.get("tasks", []),
    )

    prompt = render_checkpoint(plan, dry_run=dry_run)

    return {
        "phase": 5,
        "status": "checkpoint",
        "prompt": prompt,
        "dry_run": dry_run,
    }


def _phase_6(argv: list[str]) -> dict:
    """Phase 6: create beads issues from tasks.md.

    Expects JSON on stdin with source_id, summary, external_ref,
    tasks_text, and optionally dry_run.
    """
    data = json.loads(sys.stdin.read())

    tasks_text = data.get("tasks_text", "")
    tasks = parse_tasks_md(tasks_text) if tasks_text else data.get("tasks", [])
    dry_run = data.get("dry_run", False)

    result = create_issues(
        source_id=data["source_id"],
        summary=data["summary"],
        external_ref=data["external_ref"],
        tasks=tasks,
        dry_run=dry_run,
    )

    return {
        "phase": 6,
        "status": "created",
        "epic_id": result.epic_id,
        "issues": [
            {
                "id": issue.id,
                "title": issue.title,
                "type": issue.issue_type,
                "parent_id": issue.parent_id,
            }
            for issue in result.issues
        ],
    }


def _phase_10(argv: list[str]) -> dict:
    """Phase 10: detect dev server and render verification checklist.

    Expects JSON on stdin with worktree_path, claude_md_text,
    and check_items.
    """
    data = json.loads(sys.stdin.read())

    dev_info = detect_dev_command(
        worktree_path=data["worktree_path"],
        claude_md_text=data.get("claude_md_text", ""),
    )

    checklist = render_verification_checklist(
        dev_info=dev_info,
        worktree_path=data["worktree_path"],
        check_items=data.get("check_items", []),
    )

    return {
        "phase": 10,
        "status": "ready",
        "command": dev_info.command,
        "url": dev_info.url,
        "detected_from": dev_info.detected_from,
        "checklist": checklist,
    }


_PHASE_DISPATCH = {
    "0": _phase_0,
    "5": _phase_5,
    "6": _phase_6,
    "10": _phase_10,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(
            json.dumps({"error": "Usage: python3 -m dark_factory <init|run|phase> [args...]"}),
            file=sys.stderr,
        )
        sys.exit(1)

    phase = sys.argv[1]
    rest = sys.argv[2:]

    # "init" sub-command: scaffold Claude Code integration
    if phase == "init":
        from .init import run_init
        run_init(rest[0] if rest else ".")
        return

    # "run" sub-command: full pipeline execution
    if phase == "run":
        _run_full_pipeline(rest)
        return

    handler = _PHASE_DISPATCH.get(phase)
    if handler is None:
        print(
            json.dumps({"error": f"Unknown phase: {phase}. Available: {sorted(_PHASE_DISPATCH.keys())} + ['init', 'run']"}),
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = handler(rest)
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(
            json.dumps({"phase": int(phase), "status": "error", "error": str(exc)}),
            file=sys.stderr,
        )
        sys.exit(1)


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string if missing."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _run_full_pipeline(argv: list[str]) -> None:
    """Execute the full Dark Factory pipeline end-to-end.

    This is the entry point for ``python3 -m dark_factory run <args>``.
    Prints the completion summary on success or failure.

    Phase sequence: 0 → 1 → 1.5 → 2 → 3 → 4 → 5 → 6 → 6.5 → 7 → 8 → 9 → 10 → 11
    Sub-phase routing (handled by run_phase): 1→1.5, 1.5→2, 6→6.5, 6.5→7
    """
    from .orchestrator import CompletionSummary, PHASE_NAMES, diff_size_guard
    from .pipeline import (
        run_phase,
        run_phase_1_5,
        run_phase_6_5,
        run_phase_7,
        run_phase_9,
    )
    from .pr import run_phase_11
    from .verify import (
        HoldoutDecision,
        parse_holdout_decision,
        render_holdout_warning,
        verify_tests,
    )

    summary = CompletionSummary()
    pipeline_start = time.monotonic()

    # Intermediate results threaded between phases
    ticket: TicketFields | None = None
    exploration_output: str = ""
    plan_review_verdict: str = "PASS"

    try:
        # ── Phase 0: Arg parsing, tool checks, state init ──────────────
        phase_start = time.monotonic()
        args = parse_args(argv)
        if args.missing_tools:
            summary.add_phase(0, PHASE_NAMES[0], status="failed",
                              duration_s=time.monotonic() - phase_start)
            summary.final_status = "failed"
            summary.error_phase = 0
            summary.error_message = f"Missing tools: {', '.join(args.missing_tools)}"
            print(summary.render(), file=sys.stderr)
            sys.exit(1)

        state = PipelineState(
            source=args.source,
            repo_root=".",
            dry_run=args.dry_run,
        )

        if args.resume:
            state_path = state._state_path()
            if state_path.exists():
                state = PipelineState.load(state_path)
                state.error = None  # clear previous error for retry

        summary.add_phase(0, PHASE_NAMES[0],
                          duration_s=time.monotonic() - phase_start)

        source_id_lower = args.source.id
        external_ref = f"{args.source.kind}:{args.source.raw}"

        # ── Phase 1: Source Ingestion ──────────────────────────────────
        if not state.is_phase_completed(1):
            async def _ingest() -> TicketFields:
                if args.source.kind == "jira":
                    return ingest_jira(args.source.raw)
                elif args.source.kind == "file":
                    return ingest_file(args.source.raw)
                return await ingest_inline(args.source.raw, dry_run=state.dry_run)

            phase_start = time.monotonic()
            ticket = asyncio.run(run_phase(state, 1, _ingest))
            summary.add_phase(1, PHASE_NAMES[1],
                              duration_s=time.monotonic() - phase_start)
        else:
            # Resume: reconstruct ticket from source
            if args.source.kind == "file":
                ticket = ingest_file(args.source.raw)
            else:
                ticket = TicketFields(summary=args.source.raw,
                                      description=args.source.raw)

        # ── Phase 1.5: Input Quality Gate ──────────────────────────────
        if not state.is_phase_completed(1.5):
            phase_start = time.monotonic()
            readiness = asyncio.run(run_phase(
                state, 1.5, run_phase_1_5, state, ticket,
                dry_run=state.dry_run,
            ))
            summary.add_phase(1.5, PHASE_NAMES[1.5],
                              duration_s=time.monotonic() - phase_start)
            if readiness.status == "not_ready":
                raise PipelineError(
                    1.5, f"Input quality gate failed (score={readiness.score}): "
                         f"{readiness.gaps}")

        # ── Phase 2: Codebase Exploration (2a + 2b) ────────────────────
        if not state.is_phase_completed(2):
            async def _explore():
                bundle = prefetch_context(state.repo_root, ticket=ticket)
                expl = await explore_codebase(
                    state.repo_root, bundle, ticket, dry_run=state.dry_run)
                return bundle, expl

            phase_start = time.monotonic()
            _bundle, exploration = asyncio.run(run_phase(state, 2, _explore))
            exploration_output = exploration.get("exploration_output", "")
            summary.add_phase(2, PHASE_NAMES[2],
                              duration_s=time.monotonic() - phase_start)

        # ── Phase 3: Scaffold & OpenSpec ───────────────────────────────
        if not state.is_phase_completed(3):
            phase_start = time.monotonic()
            scaffold = asyncio.run(run_phase(
                state, 3, run_phase_3,
                state, source_id_lower, ticket.summary, ticket.description,
                ticket.acceptance_criteria, external_ref, exploration_output,
                dry_run=state.dry_run,
            ))
            summary.add_phase(3, PHASE_NAMES[3],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=scaffold.scaffold_cost_usd)

        change_id = f"dark-factory-{source_id_lower}"

        # ── Phase 4: Plan Review Gate ──────────────────────────────────
        if not state.is_phase_completed(4):
            phase_start = time.monotonic()
            plan_review = asyncio.run(run_phase(
                state, 4, run_phase_4,
                state.worktree_path, change_id, external_ref, ticket.summary,
                ticket.acceptance_criteria, exploration_output,
                dry_run=state.dry_run,
            ))
            plan_review_verdict = plan_review.verdict
            summary.add_phase(4, PHASE_NAMES[4],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=plan_review.review_cost_usd)

        # ── Read openspec artifacts from disk ──────────────────────────
        change_dir = Path(state.worktree_path) / "openspec" / "changes" / change_id
        spec_text = _read_safe(change_dir / "specs" / "main" / "spec.md")
        tasks_text = _read_safe(change_dir / "tasks.md")

        # ── Phase 5: Human Checkpoint ──────────────────────────────────
        if not state.is_phase_completed(5):
            phase_start = time.monotonic()
            plan = PlanSummary(
                external_ref=external_ref,
                summary=ticket.summary,
                branch=state.branch,
                worktree_path=state.worktree_path,
                review_result=plan_review_verdict,
                spec_overview=spec_text[:200] if spec_text else "",
                requirements=parse_spec_requirements(spec_text),
                tasks=parse_tasks(tasks_text),
            )
            prompt = render_checkpoint(plan, dry_run=state.dry_run)
            print(prompt, file=sys.stderr)

            if state.dry_run:
                # Dry-run exit point: complete through Phase 5 then stop
                summary.add_phase(5, PHASE_NAMES[5],
                                  duration_s=time.monotonic() - phase_start)
                summary.final_status = "success"
                summary.total_duration_s = time.monotonic() - pipeline_start
                print(json.dumps({
                    "status": "dry_run_complete",
                    "source": args.source.__dict__,
                    "phases_completed": state.completed_phases + [5],
                    "summary": ticket.summary,
                }, indent=2))
                print(summary.render(), file=sys.stderr)
                sys.exit(0)

            # Read human decision from stdin
            response = input().strip()
            decision = parse_decision(response)

            if decision == Decision.ABORT:
                summary.add_phase(5, PHASE_NAMES[5],
                                  duration_s=time.monotonic() - phase_start,
                                  status="aborted")
                summary.final_status = "aborted"
                summary.total_duration_s = time.monotonic() - pipeline_start
                print(summary.render(), file=sys.stderr)
                sys.exit(0)
            elif decision == Decision.MODIFY:
                state.save()
                summary.add_phase(5, PHASE_NAMES[5],
                                  duration_s=time.monotonic() - phase_start,
                                  status="paused")
                print("Modification requested. Edit the spec files and "
                      "re-run with --resume.", file=sys.stderr)
                sys.exit(0)

            # APPROVE: continue
            state.completed_phases.append(5)
            state.current_phase = 6
            state.save()
            summary.add_phase(5, PHASE_NAMES[5],
                              duration_s=time.monotonic() - phase_start)

        # ── Phase 6: Issue Creation (sync) ─────────────────────────────
        task_titles = parse_tasks_md(tasks_text)
        if not state.is_phase_completed(6):
            phase_start = time.monotonic()
            issue_result = create_issues(
                source_id=source_id_lower,
                summary=ticket.summary,
                external_ref=external_ref,
                tasks=task_titles,
                dry_run=state.dry_run,
            )
            state.epic_id = issue_result.epic_id
            state.issues = [
                {"id": i.id, "title": i.title, "type": i.issue_type,
                 "parent_id": i.parent_id}
                for i in issue_result.issues
            ]
            state.completed_phases.append(6)
            state.current_phase = 6.5
            state.save()
            summary.add_phase(6, PHASE_NAMES[6],
                              duration_s=time.monotonic() - phase_start)

        # ── Phase 6.5: Test Generation ─────────────────────────────────
        if not state.is_phase_completed(6.5):
            spec_texts = [spec_text] if spec_text else []
            phase_start = time.monotonic()
            tdd_result = asyncio.run(run_phase(
                state, 6.5, run_phase_6_5,
                state, state.worktree_path, spec_texts,
                dry_run=state.dry_run,
            ))
            summary.add_phase(6.5, PHASE_NAMES[6.5],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=tdd_result.cost_usd)

        # ── Phase 7: Implementation ────────────────────────────────────
        if not state.is_phase_completed(7):
            claude_md = Path(state.worktree_path) / "CLAUDE.md"
            sys_prompt = _read_safe(claude_md) or None
            phase_start = time.monotonic()
            impl_result = asyncio.run(run_phase(
                state, 7, run_phase_7,
                state, state.issues, state.worktree_path, sys_prompt,
                dry_run=state.dry_run,
            ))
            summary.add_phase(7, PHASE_NAMES[7],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=impl_result.total_cost_usd)

        # ── Phase 8: Test & Dep Audit ──────────────────────────────────
        if not state.is_phase_completed(8):
            claude_md = Path(state.worktree_path) / "CLAUDE.md"
            claude_md_text = _read_safe(claude_md)
            phase_start = time.monotonic()

            async def _phase_8():
                return await verify_tests(
                    state.worktree_path, claude_md_text,
                    dry_run=state.dry_run,
                    holdout_test_paths=state.holdout_test_paths or None,
                )

            verification, holdout = asyncio.run(
                run_phase(state, 8, _phase_8))
            summary.add_phase(8, PHASE_NAMES[8],
                              duration_s=time.monotonic() - phase_start)

            # Holdout warning gate
            if holdout is not None and not holdout.passed:
                warning = render_holdout_warning(holdout)
                print(warning, file=sys.stderr)
                resp = input().strip()
                holdout_decision = parse_holdout_decision(resp)
                if holdout_decision == HoldoutDecision.ABORT:
                    raise PipelineError(8, "Aborted: holdout test failures")
                elif holdout_decision == HoldoutDecision.INVESTIGATE:
                    state.save()
                    print("Paused for investigation. Re-run with --resume.",
                          file=sys.stderr)
                    summary.final_status = "paused"
                    summary.total_duration_s = time.monotonic() - pipeline_start
                    print(summary.render(), file=sys.stderr)
                    sys.exit(0)

        # ── Diff size guard (between Phase 8 and 9) ───────────────────
        diff_report = diff_size_guard(
            state.worktree_path, len(task_titles), dry_run=state.dry_run)
        if not diff_report.passed:
            print(f"WARNING: {diff_report.warning}", file=sys.stderr)

        # ── Phase 9: Implementation Review ─────────────────────────────
        if not state.is_phase_completed(9):
            phase_start = time.monotonic()
            review_result = asyncio.run(run_phase(
                state, 9, run_phase_9,
                state.worktree_path, spec_text,
                dry_run=state.dry_run,
            ))
            summary.add_phase(9, PHASE_NAMES[9],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=review_result.total_cost_usd)

        # ── Phase 10: Local Dev Verification (sync) ────────────────────
        if not state.is_phase_completed(10):
            phase_start = time.monotonic()
            claude_md = Path(state.worktree_path) / "CLAUDE.md"
            dev_info = detect_dev_command(
                state.worktree_path, _read_safe(claude_md))
            checklist = render_verification_checklist(
                dev_info=dev_info,
                worktree_path=state.worktree_path,
                check_items=ticket.acceptance_criteria,
            )
            print(checklist, file=sys.stderr)
            print("\nPress Enter to continue, or 'skip' to skip:",
                  file=sys.stderr)
            input()

            state.completed_phases.append(10)
            state.current_phase = 11
            state.save()
            summary.add_phase(10, PHASE_NAMES[10],
                              duration_s=time.monotonic() - phase_start)

        # ── Phase 11: PR Creation ──────────────────────────────────────
        pr_result = None
        if not state.is_phase_completed(11):
            issue_ids = [i["id"] for i in state.issues
                         if i.get("type") != "epic"]
            phase_start = time.monotonic()
            pr_result = asyncio.run(run_phase(
                state, 11, run_phase_11,
                state.repo_root, state.worktree_path, state.branch,
                source_id_lower, ticket.summary, external_ref, issue_ids,
                dry_run=state.dry_run,
            ))
            summary.add_phase(11, PHASE_NAMES[11],
                              duration_s=time.monotonic() - phase_start,
                              cost_usd=pr_result.cost_usd)

        # ── Final output ──────────────────────────────────────────────
        summary.final_status = "success"
        summary.total_duration_s = time.monotonic() - pipeline_start
        summary.total_cost_usd = state.total_cost_usd
        print(summary.render(), file=sys.stderr)

        print(json.dumps({
            "status": "success",
            "pr_url": pr_result.pr_url if pr_result else "",
            "branch": state.branch,
            "source": args.source.__dict__,
            "phases_completed": state.completed_phases,
            "total_cost_usd": state.total_cost_usd,
        }, indent=2))

    except PipelineError as exc:
        summary.final_status = "failed"
        summary.error_phase = exc.phase
        summary.error_message = str(exc)
        summary.total_duration_s = time.monotonic() - pipeline_start
        print(summary.render(), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        summary.final_status = "failed"
        summary.error_phase = getattr(state, "current_phase", 0) if "state" in dir() else 0
        summary.error_message = str(exc)
        summary.total_duration_s = time.monotonic() - pipeline_start
        print(summary.render(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
