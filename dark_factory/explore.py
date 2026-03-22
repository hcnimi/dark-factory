"""Phase 2: context pre-fetch (2a, deterministic) and SDK exploration (2b).

Phase 2a collects repo structure, project metadata, CI config, test
infrastructure, convention files, and recent git history -- no LLM needed.
Phase 2b passes the context bundle to an SDK exploration call.

Context engineering layers (import graph, test mapping, symbol extraction)
live in context_engineering.py and are re-exported here for backward
compatibility.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .ingest import TicketFields, extract_keywords, search_codebase_for_keywords

# Re-export context engineering public API so existing imports keep working
from .context_engineering import (  # noqa: F401
    _detect_language,
    _extract_symbols_go,
    _extract_symbols_python,
    _extract_symbols_ts,
    _find_test_by_convention,
    _find_test_by_import_scan,
    _is_test_file,
    _parse_imports_go,
    _parse_imports_python,
    _parse_imports_ts,
    _resolve_import,
    build_import_graph,
    build_reverse_dependency_map,
    build_symbol_context,
    build_test_mapping,
)

# Also import _read_file_safe from context_engineering (canonical location),
# but define a local alias used by the collection helpers in this module.
from .context_engineering import _read_file_safe  # noqa: F401


# ---------------------------------------------------------------------------
# Context bundle dataclass
# ---------------------------------------------------------------------------

@dataclass
class ContextBundle:
    """Structured context collected deterministically in Phase 2a."""

    repo_root: str = ""
    directory_tree: str = ""
    root_docs: list[str] = field(default_factory=list)
    project_metadata: dict[str, Any] = field(default_factory=dict)
    ci_configs: dict[str, str] = field(default_factory=dict)
    test_infrastructure: dict[str, Any] = field(default_factory=dict)
    convention_files: dict[str, str] = field(default_factory=dict)
    recent_commits: list[str] = field(default_factory=list)
    recently_added_files: list[str] = field(default_factory=list)
    keyword_matches: list[str] = field(default_factory=list)
    import_graph: dict[str, list[str]] = field(default_factory=dict)
    test_mapping: dict[str, str | None] = field(default_factory=dict)
    symbol_context: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt_text(self) -> str:
        """Format the bundle as text for injection into an agent's system prompt."""
        sections = []

        sections.append("## Repository Structure")
        sections.append(self.directory_tree or "(not collected)")

        if self.root_docs:
            sections.append("## Root Documentation")
            sections.append(", ".join(self.root_docs))

        if self.project_metadata:
            sections.append("## Project Metadata")
            sections.append(json.dumps(self.project_metadata, indent=2, default=str))

        if self.ci_configs:
            sections.append("## CI/CD Configuration")
            for path, content in self.ci_configs.items():
                sections.append(f"### {path}")
                sections.append(content)

        if self.test_infrastructure:
            sections.append("## Test Infrastructure")
            sections.append(json.dumps(self.test_infrastructure, indent=2, default=str))

        if self.convention_files:
            sections.append("## Convention Files")
            for path, content in self.convention_files.items():
                sections.append(f"### {path}")
                sections.append(content)

        if self.recent_commits:
            sections.append("## Recent Commits (last 20)")
            sections.append("\n".join(self.recent_commits))

        if self.recently_added_files:
            sections.append("## Recently Added Files")
            sections.append("\n".join(self.recently_added_files))

        if self.keyword_matches:
            sections.append("## Keyword-Matched Files")
            sections.append("\n".join(self.keyword_matches))

        if self.import_graph:
            sections.append("## Import Graph")
            for file_path, imports in sorted(self.import_graph.items()):
                sections.append(f"  {file_path} → {', '.join(imports)}")

        if self.test_mapping:
            sections.append("## Test-Source Mapping")
            for source, test in sorted(self.test_mapping.items()):
                status = test if test else "(no test found)"
                sections.append(f"  {source} → {status}")

        if self.symbol_context:
            # Build reverse dependency map for "Used by:" annotations
            reverse_deps = build_reverse_dependency_map(self.import_graph)

            sections.append("## API Surface (Symbol Context)")
            lines = []
            for file_path, signatures in sorted(self.symbol_context.items()):
                lines.append(f"── {file_path} ──")
                importers = reverse_deps.get(file_path, [])
                if importers:
                    lines.append(f"  Used by: {', '.join(importers)}")
                for sig in signatures:
                    lines.append(f"  {sig}")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Phase 2a: deterministic pre-fetch
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str, *, timeout: int = 15) -> str:
    """Run a git command and return stdout, empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _collect_directory_tree(repo_root: Path) -> str:
    """Top-level directory listing (depth 2) using find."""
    try:
        result = subprocess.run(
            ["find", ".", "-maxdepth", "2", "-not", "-path", "./.git/*",
             "-not", "-path", "./node_modules/*", "-not", "-path", "./.venv/*",
             "-not", "-name", ".git"],
            capture_output=True, text=True, cwd=str(repo_root), timeout=10,
        )
        if result.returncode == 0:
            lines = sorted(result.stdout.strip().splitlines())
            return "\n".join(lines[:200])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _collect_root_docs(repo_root: Path) -> list[str]:
    """Find markdown files at depth 1-2."""
    docs = []
    for pattern in ["*.md", "*/*.md"]:
        docs.extend(str(p.relative_to(repo_root)) for p in repo_root.glob(pattern)
                     if p.is_file() and ".git" not in str(p))
    return sorted(set(docs))[:30]


def _collect_project_metadata(repo_root: Path) -> dict[str, Any]:
    """Parse package.json, pyproject.toml, or go.mod for project info."""
    metadata: dict[str, Any] = {}

    # package.json
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            metadata["package_json"] = {
                "name": data.get("name", ""),
                "scripts": data.get("scripts", {}),
                "dependencies": list((data.get("dependencies") or {}).keys()),
                "devDependencies": list((data.get("devDependencies") or {}).keys()),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # pyproject.toml -- basic parsing without toml library
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        content = _read_file_safe(pyproject)
        metadata["pyproject_toml"] = {"raw": content[:5000]}
        # Extract project name if present
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("name") and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                metadata["pyproject_toml"]["name"] = val
                break

    # go.mod
    go_mod = repo_root / "go.mod"
    if go_mod.exists():
        content = _read_file_safe(go_mod)
        metadata["go_mod"] = {"raw": content[:5000]}
        for line in content.splitlines():
            if line.startswith("module "):
                metadata["go_mod"]["module"] = line.split(None, 1)[1].strip()
                break

    return metadata


def _collect_ci_configs(repo_root: Path) -> dict[str, str]:
    """Collect CI/CD configuration files -- always included when present."""
    ci_files: dict[str, str] = {}

    # Direct files at repo root
    for name in ("blackbird.yaml", "buildspec.yml", "Dockerfile",
                 ".travis.yml", "Jenkinsfile", "Makefile"):
        path = repo_root / name
        if path.exists():
            ci_files[name] = _read_file_safe(path)

    # GitHub Actions workflows
    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for wf in sorted(workflows_dir.iterdir()):
            if wf.suffix in (".yml", ".yaml") and wf.is_file():
                rel = str(wf.relative_to(repo_root))
                ci_files[rel] = _read_file_safe(wf)

    # CircleCI
    circleci = repo_root / ".circleci" / "config.yml"
    if circleci.exists():
        ci_files[str(circleci.relative_to(repo_root))] = _read_file_safe(circleci)

    return ci_files


def _collect_test_infrastructure(repo_root: Path) -> dict[str, Any]:
    """Detect test config files and extract test/lint commands from metadata."""
    infra: dict[str, Any] = {"config_files": [], "commands": {}}

    # Test config file patterns
    test_configs = [
        "jest.config.js", "jest.config.ts", "jest.config.mjs",
        "vitest.config.ts", "vitest.config.js", "vitest.config.mjs",
        "pytest.ini", "conftest.py", "setup.cfg",
        ".nycrc", ".nycrc.json", "karma.conf.js",
        "cypress.config.ts", "cypress.config.js",
        "playwright.config.ts", "playwright.config.js",
    ]

    for name in test_configs:
        if (repo_root / name).exists():
            infra["config_files"].append(name)

    # Also check for pyproject.toml [tool.pytest] sections
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        content = _read_file_safe(pyproject)
        if "[tool.pytest" in content:
            infra["config_files"].append("pyproject.toml [tool.pytest]")

    # Extract test/lint commands from package.json scripts
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            for key in ("test", "test:unit", "test:e2e", "test:integration",
                        "lint", "lint:fix", "check", "typecheck", "type-check"):
                if key in scripts:
                    infra["commands"][key] = scripts[key]
        except (json.JSONDecodeError, OSError):
            pass

    # Extract from Makefile targets
    makefile = repo_root / "Makefile"
    if makefile.exists():
        content = _read_file_safe(makefile, max_bytes=10_000)
        for line in content.splitlines():
            if line.startswith(("test:", "lint:", "check:")):
                target = line.split(":")[0]
                infra["commands"][f"make {target}"] = line

    return infra


def _collect_convention_files(repo_root: Path) -> dict[str, str]:
    """Read CLAUDE.md, AGENTS.md, .cursorrules, and similar convention files."""
    conventions: dict[str, str] = {}

    for name in ("CLAUDE.md", "AGENTS.md", ".cursorrules", ".editorconfig",
                 ".prettierrc", ".prettierrc.json", ".eslintrc.json",
                 ".eslintrc.js", ".eslintrc.yml"):
        path = repo_root / name
        if path.exists():
            conventions[name] = _read_file_safe(path)

    # .claude/CLAUDE.md (project-level)
    project_claude = repo_root / ".claude" / "CLAUDE.md"
    if project_claude.exists():
        conventions[".claude/CLAUDE.md"] = _read_file_safe(project_claude)

    return conventions


def _collect_recent_git_history(repo_root: str) -> tuple[list[str], list[str]]:
    """Collect 20 most recent commits and recently added files from last 10 commits."""
    commits = _run_git(
        ["log", "--oneline", "-20", "--no-decorate"],
        cwd=repo_root,
    )
    recent_commits = commits.splitlines() if commits else []

    # Files added in the last 10 commits
    added = _run_git(
        ["log", "--diff-filter=A", "--name-only", "--pretty=format:", "-10"],
        cwd=repo_root,
    )
    recently_added = [f for f in added.splitlines() if f.strip()] if added else []
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for f in recently_added:
        if f not in seen:
            seen.add(f)
            deduped.append(f)

    return recent_commits, deduped


def prefetch_context(
    repo_root: str,
    ticket: TicketFields | None = None,
) -> ContextBundle:
    """Phase 2a: deterministic context collection -- no LLM tokens consumed.

    Collects repo structure, project metadata, CI config, test infrastructure,
    convention files, recent git history, and keyword-matched files.
    """
    root = Path(repo_root)
    bundle = ContextBundle(repo_root=repo_root)

    bundle.directory_tree = _collect_directory_tree(root)
    bundle.root_docs = _collect_root_docs(root)
    bundle.project_metadata = _collect_project_metadata(root)
    bundle.ci_configs = _collect_ci_configs(root)
    bundle.test_infrastructure = _collect_test_infrastructure(root)
    bundle.convention_files = _collect_convention_files(root)

    recent_commits, recently_added = _collect_recent_git_history(repo_root)
    bundle.recent_commits = recent_commits
    bundle.recently_added_files = recently_added

    # Keyword search from ticket content
    if ticket:
        keywords = extract_keywords(ticket)
        bundle.keyword_matches = search_codebase_for_keywords(
            keywords, repo_root, max_results=20,
        )

    # Context engineering layers: import graph -> test mapping -> symbol context
    # Seed files are keyword matches (already repo-relative paths)
    if bundle.keyword_matches:
        bundle.import_graph = build_import_graph(bundle.keyword_matches, repo_root)

        # Neighborhood = all files in the import graph
        neighborhood = list(bundle.import_graph.keys())

        bundle.test_mapping = build_test_mapping(neighborhood, repo_root)
        bundle.symbol_context = build_symbol_context(
            neighborhood,
            repo_root,
            import_graph=bundle.import_graph,
            seed_files=bundle.keyword_matches,
        )

    return bundle


# ---------------------------------------------------------------------------
# Phase 2b: SDK exploration call
# ---------------------------------------------------------------------------

_EXPLORATION_SYSTEM_PROMPT_TEMPLATE = """\
You are a codebase exploration agent. Your job is to understand the architecture,
module boundaries, and patterns of this repository so that a subsequent implementation
agent can work effectively.

The following context has already been collected deterministically. DO NOT re-read
these files -- they are already provided below:

{context_bundle}

## Your Task

The context above now includes an import graph, test-source mapping, and API surface
view (symbol context) when available. Use these to orient quickly.

Explore what is NOT covered above:
1. Architectural patterns (API structure, data flow, state management)
2. Code conventions (naming, error handling, logging patterns)
3. Integration points relevant to the ticket
4. Any missing context the import graph or symbol context didn't capture

Focus on understanding, not modifying. Return a structured analysis.

## Ticket Summary
{ticket_summary}

## Acceptance Criteria
{acceptance_criteria}
"""


async def explore_codebase(
    repo_root: str,
    bundle: ContextBundle,
    ticket: TicketFields,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Phase 2b: SDK exploration call with pre-fetched context.

    Uses sonnet, max_turns=5, allowed_tools=["Read", "Glob", "Grep"].
    Reduced from 15 turns — import graph, test mapping, and symbol context
    now front-load most of the structural analysis.
    """
    if dry_run:
        return {
            "status": "dry_run",
            "bundle": bundle.to_dict(),
            "ticket": ticket.to_dict(),
        }

    system_prompt = _EXPLORATION_SYSTEM_PROMPT_TEMPLATE.format(
        context_bundle=bundle.to_prompt_text(),
        ticket_summary=ticket.summary,
        acceptance_criteria="\n".join(
            f"- {ac}" for ac in ticket.acceptance_criteria
        ),
    )

    try:
        from claude_code_sdk import ClaudeCodeOptions, query
    except ImportError:
        # SDK not available -- return the bundle as-is
        return {
            "status": "sdk_unavailable",
            "bundle": bundle.to_dict(),
            "ticket": ticket.to_dict(),
        }

    messages: list[str] = []
    async for msg in query(
        prompt=(
            f"Explore this codebase to understand architecture and patterns "
            f"relevant to: {ticket.summary}"
        ),
        options=ClaudeCodeOptions(
            model="sonnet",
            # Reduced from spec's 15 to 5: import graph + symbol context
            # front-loads structural analysis, reducing exploration turns needed.
            max_turns=5,
            allowed_tools=["Read", "Glob", "Grep"],
            system_prompt=system_prompt,
            cwd=repo_root,
        ),
    ):
        if hasattr(msg, "content"):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            messages.append(content)

    return {
        "status": "completed",
        "exploration_output": "\n".join(messages),
        "bundle": bundle.to_dict(),
    }
