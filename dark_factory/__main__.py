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

    test_cmd = detect_test_command(repo_root)
    claude_md = Path(repo_root) / "CLAUDE.md"

    print(f"Initialized .dark-factory/ in {repo_root}")
    print(f"  Test command: {test_cmd or '(not detected)'}")
    print(f"  CLAUDE.md: {'present' if claude_md.exists() else 'missing (recommended)'}")


def cmd_run(args: argparse.Namespace) -> None:
    missing = _preflight()
    if missing:
        print(f"error: missing required tools: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    repo_root = _get_repo_root()
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

    state = RunState.create(source=source, config=config)
    state.test_command = detect_test_command(repo_root)
    state.save(repo_root)

    print(f"Run {state.run_id} | source: {source.kind.value} | id: {source.id}")

    # Import here to avoid circular / heavy imports at CLI parse time
    from .intent import clarify_intent
    from .infra import run_implementation
    from .evaluator import evaluate

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
        answer = input("\nProceed with implementation? [Y/n/abort] ").strip().lower()
        if answer in ("n", "abort", "a"):
            raise DarkFactoryError("aborted by user after intent review")

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
        if report.is_borderline():
            print("\nBorderline scores detected. Options: [a]ccept / [r]e-run / [q]uit")
        else:
            print("\nOptions: [a]ccept / [q]uit")
        answer = input("Choice: ").strip().lower()
        if answer in ("q", "quit", "abort"):
            raise DarkFactoryError("aborted by user after evaluation")

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
    run_p.add_argument("input", help="Jira key, file path, or inline description")
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
