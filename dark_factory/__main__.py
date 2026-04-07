"""CLI entry point for dark-factory v2."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .types import (
    DarkFactoryError,
    Gate,
    IntentDocument,
    InterviewQA,
    RunConfig,
    RunState,
    RunStatus,
    SourceKind,
    classify_source,
    read_source_content,
)

# Exit code for "paused at gate, resume to continue" (EX_TEMPFAIL)
EXIT_GATED = 75


def _handle_gate(
    state: RunState,
    repo_root: str,
    gate_type: str,
    prompt_msg: str,
    abort_msg: str,
) -> str:
    """Handle a gate: input() on TTY, exit 75 on non-TTY."""
    if sys.stdin.isatty():
        answer = input(prompt_msg).strip().lower()
        if answer in ("n", "abort", "a", "q", "quit"):
            raise DarkFactoryError(abort_msg)
        return answer

    # Non-TTY: emit gate marker and exit for the caller to resume
    gate_info = {
        "__gate__": gate_type,
        "run_id": state.run_id,
        "state_file": str(state.state_path(repo_root)),
    }
    # Include unanswered clarification questions for the orchestrator
    if state.interview and any(not qa.answer for qa in state.interview):
        gate_info["clarifications"] = [qa.question for qa in state.interview if not qa.answer]
    print(json.dumps(gate_info))
    sys.exit(EXIT_GATED)


def _get_repo_root() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _preflight() -> list[str]:
    """Check required tools are on PATH. Returns list of missing tools."""
    missing = []
    for tool in ("git", "gh"):
        if shutil.which(tool) is None:
            missing.append(tool)
    return missing


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    from .infra import detect_test_command

    repo_root = _get_repo_root()
    state_dir = Path(repo_root) / ".dark-factory"
    state_dir.mkdir(exist_ok=True)

    gitignore = state_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# dark-factory run artifacts\n*.json\n*.jsonl\n")

    # Install/update the Claude Code slash command
    _install_command(repo_root)

    test_cmd = detect_test_command(repo_root)
    claude_md = Path(repo_root) / "CLAUDE.md"

    print(f"Initialized .dark-factory/ in {repo_root}")
    print(f"  Test command: {test_cmd or '(not detected)'}")
    print(f"  CLAUDE.md: {'present' if claude_md.exists() else 'missing (recommended)'}")


def _install_command(repo_root: str) -> None:
    """Install the /dark-factory slash command into the project's .claude/commands/."""
    template = Path(__file__).parent / "commands" / "dark-factory.md"
    if not template.exists():
        return

    dest_dir = Path(repo_root) / ".claude" / "commands"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "dark-factory.md"

    template_content = template.read_text()
    if dest.exists() and dest.read_text() == template_content:
        print("  /dark-factory command: up to date")
        return

    action = "updated" if dest.exists() else "installed"
    dest.write_text(template_content)
    print(f"  /dark-factory command: {action} -> {dest}")


def cmd_run(args: argparse.Namespace) -> None:
    missing = _preflight()
    if missing:
        print(f"error: missing required tools: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    repo_root = _get_repo_root()

    # Import here to avoid circular / heavy imports at CLI parse time
    from .infra import run_implementation
    from .evaluator import evaluate

    # --- Resume path ---
    if args.resume:
        if args.input:
            print("error: cannot use both --resume and a positional input", file=sys.stderr)
            sys.exit(1)
        state_path = Path(repo_root) / ".dark-factory" / f"{args.resume}.json"
        if not state_path.exists():
            print(f"error: no state file for run {args.resume}", file=sys.stderr)
            sys.exit(1)
        state = RunState.load(state_path)
        if state.status not in (RunStatus.GATED_INTENT, RunStatus.GATED_EVAL):
            print(
                f"error: run {args.resume} is not at a gate (status: {state.status.value})",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Resuming run {state.run_id} from {state.status.value}")
        try:
            asyncio.run(_resume_pipeline(state, repo_root, run_implementation, evaluate))
        except DarkFactoryError as e:
            state.status = RunStatus.FAILED
            state.error = str(e)
            state.save(repo_root)
            print(f"\nerror: {e}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            state.status = RunStatus.FAILED
            state.error = "interrupted by user"
            state.save(repo_root)
            print("\ninterrupted", file=sys.stderr)
            sys.exit(130)
        return

    # --- Fresh run path ---
    if not args.input:
        print("error: input is required (Jira key, file path, or description)", file=sys.stderr)
        sys.exit(1)

    source = classify_source(args.input)

    gates: list[Gate] = []
    if args.gate_intent:
        gates.append(Gate.INTENT)
    if args.gate_eval:
        gates.append(Gate.EVAL)

    config = RunConfig(
        max_cost_usd=args.max_cost,
        evaluator_model=args.evaluator_model,
        implementation_model=args.implementation_model,
        gates=gates,
        in_place=args.in_place,
        dry_run=args.dry_run,
        analyze_spec=args.analyze_spec,
    )

    from .infra import detect_test_command
    from .intent import clarify_intent

    state = RunState.create(source=source, config=config)
    state.test_command = detect_test_command(repo_root)
    state.save(repo_root)

    print(f"Run {state.run_id} | source: {source.kind.value} | id: {source.id}")

    try:
        asyncio.run(_run_pipeline(state, repo_root, clarify_intent, run_implementation, evaluate, no_assess=args.no_assess))
    except DarkFactoryError as e:
        state.status = RunStatus.FAILED
        state.error = str(e)
        state.save(repo_root)
        print(f"\nerror: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        state.status = RunStatus.FAILED
        state.error = "interrupted by user"
        state.save(repo_root)
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)


async def _run_pipeline(state, repo_root, clarify_intent, run_implementation, evaluate, *, no_assess=False):
    from .state import log_event

    # --- Source Context Preservation ---
    source_context = read_source_content(state.source)
    state.source_context_path(repo_root).write_text(source_context)

    # --- Input Assessment (default on, --no-assess skips) ---
    interview_context = None
    if not no_assess:
        print("\n--- Input Assessment ---")
        from .interview import assess_and_probe, collect_answers_tty, format_amplification_context
        try:
            questions, assess_cost = await assess_and_probe(state.source)
            state.cost_usd += assess_cost

            if questions:
                if sys.stdin.isatty():
                    print(f"  {len(questions)} clarifying question(s):")
                    qas = collect_answers_tty(questions)
                    state.interview = qas
                    interview_context = format_amplification_context(qas)
                    log_event(state, repo_root, "interview_complete", {"qa_count": len(qas)})
                else:
                    # Non-TTY: store unanswered questions for the orchestrator.
                    # interview_context intentionally stays None here — the
                    # slash-command orchestrator will present these at the gate,
                    # collect answers, and write them to the state file before
                    # resuming. See commands/dark-factory.md Step 3.
                    state.interview = [InterviewQA(question=q, answer="") for q in questions]
                    log_event(state, repo_root, "clarifications_recommended",
                              {"questions": questions})
            else:
                print("  Input is clear — no clarification needed")
                log_event(state, repo_root, "assessment_clear", {})
        except (DarkFactoryError, OSError) as e:
            print(f"  Assessment skipped ({e})")
            log_event(state, repo_root, "assessment_failed", {"error": str(e)})

    # --- Intent Clarification ---
    print("\n--- Intent Clarification ---")
    intent, intent_cost = await clarify_intent(state.source, interview_context)
    state.intent = intent
    state.cost_usd += intent_cost
    state.status = RunStatus.INTENT_COMPLETE
    state.save(repo_root)
    log_event(state, repo_root, "intent_complete", {"intent": intent.to_dict()})

    print(intent.format_for_display())

    # --- Spec Analysis (opt-in) ---
    if state.config.analyze_spec:
        print("\n--- Spec Analysis ---")
        from .spec_analyzer import analyze_spec
        analysis = await analyze_spec(intent, state.config.evaluator_model)
        state.spec_analysis = analysis
        state.cost_usd += analysis.cost_usd
        state.save(repo_root)
        log_event(state, repo_root, "spec_analysis_complete", {"report": analysis.to_dict()})
        print(analysis.format_for_display())
        if analysis.has_warnings():
            print("\n  Warning: Some spec dimensions scored below 7.")

    # Human gate after intent
    if Gate.INTENT in state.config.gates:
        state.status = RunStatus.GATED_INTENT
        state.save(repo_root)
        log_event(state, repo_root, "gated_intent", {})
        _handle_gate(state, repo_root, "intent",
                     "\nProceed with implementation? [Y/n/abort] ",
                     "aborted by user after intent review")

    # Dry run stops after intent clarification
    if state.config.dry_run:
        state.status = RunStatus.COMPLETE
        state.save(repo_root)
        log_event(state, repo_root, "dry_run_complete", {
            "cost_usd": state.cost_usd,
            "status": state.status.value,
        })
        print(f"\nDry run {state.run_id} complete | cost: ${state.cost_usd:.4f}")
        print(json.dumps(state.to_dict(), indent=2))
        return

    await _implement_eval_complete(state, repo_root, run_implementation, evaluate, source_context, log_event)


async def _implement_eval_complete(state, repo_root, run_implementation, evaluate, source_context, log_event):
    """Shared flow: implementation -> evaluation -> eval gate -> complete."""
    # --- Implementation ---
    print("\n--- Implementation ---")
    state.status = RunStatus.IMPLEMENTING
    state.save(repo_root)
    log_event(state, repo_root, "implementation_started", {})

    intent = state.intent
    diff = await run_implementation(state, intent, repo_root)
    state.diff = diff
    state.status = RunStatus.VERIFYING
    state.save(repo_root)
    log_event(state, repo_root, "implementation_complete", {"diff_lines": len(diff.splitlines())})

    # Budget check: skip evaluation if limit reached (diff is preserved)
    if state.cost_usd >= state.config.max_cost_usd:
        print(f"\n  Budget limit reached (${state.cost_usd:.2f} >= ${state.config.max_cost_usd:.2f})")
        print("  Skipping evaluation. Diff is preserved for manual review.")
        state.diff_path(repo_root).write_text(diff)
        state.status = RunStatus.COMPLETE
        state.save(repo_root)
        log_event(state, repo_root, "budget_exceeded", {"cost_usd": state.cost_usd})
        print(f"\nRun {state.run_id} complete (budget exceeded) | cost: ${state.cost_usd:.4f}")
        print(json.dumps(state.to_dict(), indent=2))
        return

    # --- Evaluation ---
    print("\n--- Evaluation ---")
    state.status = RunStatus.EVALUATING
    state.save(repo_root)

    report = await evaluate(intent, diff, state.config.evaluator_model, source_context=source_context)
    state.evaluation = report
    state.cost_usd += report.cost_usd
    state.save(repo_root)
    log_event(state, repo_root, "evaluation_complete", {"report": report.to_dict()})

    # Save evaluation report
    eval_path = state.evaluation_path(repo_root)
    eval_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")

    print(report.format_for_display())

    # Human gate after evaluation
    if Gate.EVAL in state.config.gates:
        state.diff_path(repo_root).write_text(state.diff)
        state.status = RunStatus.GATED_EVAL
        state.save(repo_root)
        log_event(state, repo_root, "gated_eval", {})
        if report.is_borderline():
            prompt = "\nBorderline scores detected. Options: [a]ccept / [r]e-run / [q]uit\nChoice: "
        else:
            prompt = "\nOptions: [a]ccept / [q]uit\nChoice: "
        _handle_gate(state, repo_root, "eval", prompt,
                     "aborted by user after evaluation")

    # --- Complete ---
    state.status = RunStatus.COMPLETE
    state.save(repo_root)
    log_event(state, repo_root, "run_complete", {
        "cost_usd": state.cost_usd,
        "status": state.status.value,
    })

    print(f"\nRun {state.run_id} complete | cost: ${state.cost_usd:.4f}")
    print(json.dumps(state.to_dict(), indent=2))


async def _resume_pipeline(state, repo_root, run_implementation, evaluate):
    """Resume a pipeline that was paused at a gate."""
    from .state import log_event

    # Load preserved source context for evaluation
    ctx_path = state.source_context_path(repo_root)
    source_context = ctx_path.read_text() if ctx_path.exists() else ""

    log_event(state, repo_root, "gate_approved", {"gate": state.status.value})

    if state.status == RunStatus.GATED_INTENT:
        # Dry run stops after intent clarification
        if state.config.dry_run:
            state.status = RunStatus.COMPLETE
            state.save(repo_root)
            log_event(state, repo_root, "dry_run_complete", {
                "cost_usd": state.cost_usd,
                "status": state.status.value,
            })
            print(f"\nDry run {state.run_id} complete | cost: ${state.cost_usd:.4f}")
            print(json.dumps(state.to_dict(), indent=2))
            return

        await _implement_eval_complete(state, repo_root, run_implementation, evaluate, source_context, log_event)
        return

    elif state.status == RunStatus.GATED_EVAL:
        # Load diff from file (not serialized in state JSON)
        diff_file = state.diff_path(repo_root)
        if diff_file.exists():
            state.diff = diff_file.read_text()

    # --- Complete ---
    state.status = RunStatus.COMPLETE
    state.save(repo_root)
    log_event(state, repo_root, "run_complete", {
        "cost_usd": state.cost_usd,
        "status": state.status.value,
    })

    print(f"\nRun {state.run_id} complete | cost: ${state.cost_usd:.4f}")
    print(json.dumps(state.to_dict(), indent=2))


def _load_state(repo_root: str, run_id: str, allowed_statuses: list[RunStatus]) -> RunState:
    """Load and validate run state. Exits on error."""
    state_path = Path(repo_root) / ".dark-factory" / f"{run_id}.json"
    if not state_path.exists():
        print(f"error: no state file for run {run_id}", file=sys.stderr)
        sys.exit(1)
    state = RunState.load(state_path)
    if state.status not in allowed_statuses:
        print(
            f"error: run {run_id} status is {state.status.value}, "
            f"expected one of: {', '.join(s.value for s in allowed_statuses)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return state


def cmd_prepare(args: argparse.Namespace) -> None:
    """Prepare workspace and prompt files for phased implementation."""
    repo_root = _get_repo_root()
    state = _load_state(repo_root, args.run_id, [RunStatus.GATED_INTENT])

    from .infra import setup_workspace, _build_implementation_prompt, IMPLEMENTATION_SYSTEM_PROMPT
    from .state import log_event

    try:
        work_dir = setup_workspace(state, repo_root)

        ctx_path = state.source_context_path(repo_root)
        source_context = ctx_path.read_text() if ctx_path.exists() else ""
        prompt = _build_implementation_prompt(state.intent, work_dir, source_context)
        prompt_file = state.prompt_path(repo_root)
        prompt_file.write_text(prompt)

        system_file = state.system_prompt_path(repo_root)
        system_file.write_text(IMPLEMENTATION_SYSTEM_PROMPT)

        state.status = RunStatus.PREPARED
        state.save(repo_root)
        log_event(state, repo_root, "prepared", {"work_dir": work_dir})

        print(json.dumps({
            "run_id": state.run_id,
            "work_dir": work_dir,
            "branch": state.branch,
            "prompt_file": str(prompt_file),
            "system_prompt_file": str(system_file),
        }))
    except DarkFactoryError as e:
        state.status = RunStatus.FAILED
        state.error = str(e)
        state.save(repo_root)
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_verify(args: argparse.Namespace) -> None:
    """Run tests and capture diff for a prepared run."""
    repo_root = _get_repo_root()
    state = _load_state(repo_root, args.run_id, [RunStatus.PREPARED, RunStatus.VERIFYING])

    from .infra import detect_test_command, run_tests
    from .state import log_event

    try:
        work_dir = state.worktree_path
        if not work_dir:
            print(f"error: run {args.run_id} has no worktree_path", file=sys.stderr)
            sys.exit(1)

        test_cmd = state.test_command or detect_test_command(work_dir)
        passed, test_output = run_tests(test_cmd, work_dir)

        # Capture diff
        diff_result = subprocess.run(
            ["git", "diff", f"{state.base_branch}...HEAD"],
            capture_output=True, text=True, cwd=work_dir,
        )
        diff = diff_result.stdout
        if not diff.strip():
            diff_result = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True, text=True, cwd=work_dir,
            )
            diff = diff_result.stdout

        state.diff_path(repo_root).write_text(diff)
        state.status = RunStatus.VERIFYING
        state.save(repo_root)
        log_event(state, repo_root, "verify", {
            "tests_passed": passed,
            "diff_lines": len(diff.splitlines()),
        })

        print(json.dumps({
            "run_id": state.run_id,
            "tests_passed": passed,
            "test_output": test_output[-3000:],
            "diff_lines": len(diff.splitlines()),
        }))
    except DarkFactoryError as e:
        state.status = RunStatus.FAILED
        state.error = str(e)
        state.save(repo_root)
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_complete(args: argparse.Namespace) -> None:
    """Complete a run after evaluation approval."""
    repo_root = _get_repo_root()
    state = _load_state(repo_root, args.run_id, [RunStatus.GATED_EVAL])

    from .infra import remove_worktree
    from .state import log_event

    # Clean up worktree if it exists and isn't the repo itself
    if state.worktree_path and state.worktree_path != repo_root:
        wt = Path(state.worktree_path)
        if wt.exists():
            remove_worktree(state.worktree_path, state.branch, repo_root)

    state.status = RunStatus.COMPLETE
    state.save(repo_root)
    log_event(state, repo_root, "run_complete", {
        "cost_usd": state.cost_usd,
        "status": state.status.value,
    })

    print(json.dumps({
        "run_id": state.run_id,
        "status": "complete",
        "branch": state.branch,
        "cost_usd": state.cost_usd,
    }))


def cmd_evaluate(args: argparse.Namespace) -> None:
    repo_root = _get_repo_root()

    # Phased flow: --run <run_id>
    if args.run:
        state = _load_state(repo_root, args.run, [RunStatus.VERIFYING])
        from .evaluator import evaluate
        from .state import log_event

        try:
            diff_file = state.diff_path(repo_root)
            if not diff_file.exists():
                raise DarkFactoryError(f"No diff file for run {args.run}")
            diff = diff_file.read_text()

            ctx_path = state.source_context_path(repo_root)
            source_context = ctx_path.read_text() if ctx_path.exists() else ""

            state.status = RunStatus.EVALUATING
            state.save(repo_root)

            report = asyncio.run(evaluate(state.intent, diff, state.config.evaluator_model, source_context=source_context))
            state.evaluation = report
            state.cost_usd += report.cost_usd
            state.save(repo_root)
            log_event(state, repo_root, "evaluation_complete", {"report": report.to_dict()})

            eval_path = state.evaluation_path(repo_root)
            eval_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")

            print(report.format_for_display())

            if Gate.EVAL in state.config.gates:
                state.diff_path(repo_root).write_text(diff)
                state.status = RunStatus.GATED_EVAL
                state.save(repo_root)
                log_event(state, repo_root, "gated_eval", {})
                _handle_gate(state, repo_root, "eval",
                             "\nAccept evaluation? [Y/n/abort] ",
                             "aborted by user after evaluation")

            state.status = RunStatus.COMPLETE
            state.save(repo_root)
            log_event(state, repo_root, "run_complete", {
                "cost_usd": state.cost_usd,
                "status": state.status.value,
            })
            print(json.dumps(state.to_dict(), indent=2))
        except DarkFactoryError as e:
            state.status = RunStatus.FAILED
            state.error = str(e)
            state.save(repo_root)
            log_event(state, repo_root, "evaluation_failed", {"error": str(e)})
            print(f"\nerror: {e}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            state.status = RunStatus.FAILED
            state.error = "interrupted by user"
            state.save(repo_root)
            print("\ninterrupted", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            state.status = RunStatus.FAILED
            state.error = str(e)
            state.save(repo_root)
            log_event(state, repo_root, "evaluation_failed", {"error": str(e)})
            print(f"\nerror (unexpected): {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Standalone branch evaluation
    if not args.branch:
        print("error: either a branch or --run <run_id> is required", file=sys.stderr)
        sys.exit(1)

    # Get diff
    result = subprocess.run(
        ["git", "diff", f"main...{args.branch}"],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        print(f"error: could not compute diff for branch {args.branch}", file=sys.stderr)
        sys.exit(1)
    diff = result.stdout

    if not diff.strip():
        print("error: no changes found on branch", file=sys.stderr)
        sys.exit(1)

    # Load or infer intent
    if args.intent:
        intent_text = Path(args.intent).read_text()
        lines = intent_text.strip().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else "Unknown"
        summary = "\n".join(lines[1:]).strip()
        intent = IntentDocument(title=title, summary=summary, acceptance_criteria=[])
    else:
        log_result = subprocess.run(
            ["git", "log", "--oneline", f"main..{args.branch}"],
            capture_output=True, text=True, cwd=repo_root,
        )
        commits = log_result.stdout.strip()
        intent = IntentDocument(
            title=f"Changes on {args.branch}",
            summary=f"Inferred from commits:\n{commits}",
            acceptance_criteria=[],
        )

    from .evaluator import evaluate
    try:
        report = asyncio.run(evaluate(intent, diff, args.evaluator_model))
        print(report.format_for_display())
        print(json.dumps(report.to_dict(), indent=2))
    except DarkFactoryError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dark-factory",
        description="Three-component autonomous spec-to-PR orchestration",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # --- init ---
    sub.add_parser("init", help="Initialize .dark-factory/ in the current repo")

    # --- run ---
    run_p = sub.add_parser("run", help="Run the full intent → implement → evaluate pipeline")
    run_p.add_argument("input", nargs="?", help="Jira key, file path, or inline description")
    run_p.add_argument("--resume", metavar="RUN_ID", help="Resume a gated run by its run ID")
    run_p.add_argument("--max-cost", type=float, default=10.0, help="Max cost in USD (default: 10)")
    run_p.add_argument("--evaluator-model", default="claude-opus-4-6", help="Model for evaluation")
    run_p.add_argument("--implementation-model", default="claude-opus-4-20250514", help="Model for implementation agent")
    run_p.add_argument("--gate-intent", action="store_true", help="Pause for approval after intent")
    run_p.add_argument("--gate-eval", action="store_true", help="Pause for approval after evaluation")
    run_p.add_argument("--in-place", action="store_true", help="Work in repo directly (no worktree)")
    run_p.add_argument("--dry-run", action="store_true", help="Plan only, no implementation")
    run_p.add_argument("--analyze-spec", action="store_true", help="Quality-check the intent before implementation")
    run_p.add_argument("--no-assess", action="store_true", help="Skip automatic input assessment")

    # --- prepare ---
    prep_p = sub.add_parser("prepare", help="Prepare workspace and prompt files for a gated run")
    prep_p.add_argument("run_id", help="Run ID to prepare")

    # --- verify ---
    ver_p = sub.add_parser("verify", help="Run tests and capture diff for a prepared run")
    ver_p.add_argument("run_id", help="Run ID to verify")

    # --- complete ---
    comp_p = sub.add_parser("complete", help="Complete a run after evaluation approval")
    comp_p.add_argument("run_id", help="Run ID to complete")

    # --- evaluate ---
    eval_p = sub.add_parser("evaluate", help="Evaluate a branch or run")
    eval_p.add_argument("branch", nargs="?", help="Branch to evaluate")
    eval_p.add_argument("--run", metavar="RUN_ID", help="Evaluate a phased run by its run ID")
    eval_p.add_argument("--intent", help="Path to intent document")
    eval_p.add_argument("--evaluator-model", default="claude-opus-4-6", help="Model for evaluation")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "complete":
        cmd_complete(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
