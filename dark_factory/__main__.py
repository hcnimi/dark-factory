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
    RunConfig,
    RunState,
    RunStatus,
    classify_source,
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
        gates=gates,
        in_place=args.in_place,
        dry_run=args.dry_run,
    )

    from .infra import detect_test_command
    from .intent import clarify_intent

    state = RunState.create(source=source, config=config)
    state.test_command = detect_test_command(repo_root)
    state.save(repo_root)

    print(f"Run {state.run_id} | source: {source.kind.value} | id: {source.id}")

    try:
        asyncio.run(_run_pipeline(state, repo_root, clarify_intent, run_implementation, evaluate))
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


async def _run_pipeline(state, repo_root, clarify_intent, run_implementation, evaluate):
    from .state import log_event

    # --- Intent Clarification ---
    print("\n--- Intent Clarification ---")
    intent = await clarify_intent(state.source)
    state.intent = intent
    state.status = RunStatus.INTENT_COMPLETE
    state.save(repo_root)
    log_event(state, repo_root, "intent_complete", {"intent": intent.to_dict()})

    print(intent.format_for_display())

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

    # --- Implementation ---
    print("\n--- Implementation ---")
    state.status = RunStatus.IMPLEMENTING
    state.save(repo_root)
    log_event(state, repo_root, "implementation_started", {})

    diff = await run_implementation(state, intent, repo_root)
    state.diff = diff
    state.status = RunStatus.VERIFYING
    state.save(repo_root)
    log_event(state, repo_root, "implementation_complete", {"diff_lines": len(diff.splitlines())})

    # --- Evaluation ---
    print("\n--- Evaluation ---")
    state.status = RunStatus.EVALUATING
    state.save(repo_root)

    report = await evaluate(intent, diff, state.config.evaluator_model)
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

        # --- Implementation ---
        print("\n--- Implementation ---")
        state.status = RunStatus.IMPLEMENTING
        state.save(repo_root)
        log_event(state, repo_root, "implementation_started", {})

        diff = await run_implementation(state, state.intent, repo_root)
        state.diff = diff
        state.status = RunStatus.VERIFYING
        state.save(repo_root)
        log_event(state, repo_root, "implementation_complete", {"diff_lines": len(diff.splitlines())})

        # --- Evaluation ---
        print("\n--- Evaluation ---")
        state.status = RunStatus.EVALUATING
        state.save(repo_root)

        report = await evaluate(state.intent, diff, state.config.evaluator_model)
        state.evaluation = report
        state.cost_usd += report.cost_usd
        state.save(repo_root)
        log_event(state, repo_root, "evaluation_complete", {"report": report.to_dict()})

        eval_path = state.evaluation_path(repo_root)
        eval_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")

        print(report.format_for_display())

        # Eval gate (if configured, still fires on resume from intent gate)
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


def cmd_evaluate(args: argparse.Namespace) -> None:
    repo_root = _get_repo_root()

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
    from .types import IntentDocument
    if args.intent:
        intent_text = Path(args.intent).read_text()
        # Parse as simple markdown: title = first heading, rest = summary, no AC
        lines = intent_text.strip().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else "Unknown"
        summary = "\n".join(lines[1:]).strip()
        intent = IntentDocument(title=title, summary=summary, acceptance_criteria=[])
    else:
        # Infer from commit messages
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
    report = asyncio.run(evaluate(intent, diff, args.evaluator_model))

    print(report.format_for_display())
    print(json.dumps(report.to_dict(), indent=2))


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
    run_p.add_argument("--evaluator-model", default="claude-sonnet-4-20250514", help="Model for evaluation")
    run_p.add_argument("--gate-intent", action="store_true", help="Pause for approval after intent")
    run_p.add_argument("--gate-eval", action="store_true", help="Pause for approval after evaluation")
    run_p.add_argument("--in-place", action="store_true", help="Work in repo directly (no worktree)")
    run_p.add_argument("--dry-run", action="store_true", help="Plan only, no implementation")

    # --- evaluate ---
    eval_p = sub.add_parser("evaluate", help="Evaluate a branch standalone")
    eval_p.add_argument("branch", help="Branch to evaluate")
    eval_p.add_argument("--intent", help="Path to intent document")
    eval_p.add_argument("--evaluator-model", default="claude-sonnet-4-20250514", help="Model for evaluation")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
