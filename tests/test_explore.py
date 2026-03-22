"""Tests for dark_factory.explore: Phase 2a pre-fetch and Phase 2b exploration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dark_factory.explore import (
    ContextBundle,
    _collect_ci_configs,
    _collect_convention_files,
    _collect_directory_tree,
    _collect_project_metadata,
    _collect_recent_git_history,
    _collect_root_docs,
    _collect_test_infrastructure,
    prefetch_context,
)
from dark_factory.ingest import TicketFields


# ---------------------------------------------------------------------------
# ContextBundle
# ---------------------------------------------------------------------------

class TestContextBundle:
    def test_to_dict(self):
        b = ContextBundle(repo_root="/tmp/repo")
        d = b.to_dict()
        assert d["repo_root"] == "/tmp/repo"
        assert isinstance(d["ci_configs"], dict)

    def test_to_prompt_text_includes_sections(self):
        b = ContextBundle(
            repo_root="/tmp/repo",
            directory_tree=".\n./src\n./tests",
            ci_configs={".github/workflows/ci.yml": "name: CI\non: push"},
            convention_files={"CLAUDE.md": "# Instructions"},
            recent_commits=["abc1234 feat: add login"],
        )
        text = b.to_prompt_text()
        assert "Repository Structure" in text
        assert "CI/CD Configuration" in text
        assert "Convention Files" in text
        assert "Recent Commits" in text
        assert "name: CI" in text
        assert "# Instructions" in text

    def test_to_prompt_text_empty_bundle(self):
        b = ContextBundle()
        text = b.to_prompt_text()
        assert "Repository Structure" in text
        assert "(not collected)" in text


# ---------------------------------------------------------------------------
# Fixture: create a realistic repo directory structure
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_repo(tmp_path):
    """Create a minimal repo structure for testing pre-fetch."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # package.json
    (repo / "package.json").write_text(json.dumps({
        "name": "test-app",
        "scripts": {"test": "jest", "lint": "eslint ."},
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"jest": "^29.0.0", "eslint": "^8.0.0"},
    }))

    # CI config
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n")

    # Test infrastructure
    (repo / "jest.config.js").write_text("module.exports = { testEnvironment: 'node' };\n")

    # Convention files
    (repo / "CLAUDE.md").write_text("# Project Instructions\nFollow these rules.\n")

    # Source files
    src = repo / "src"
    src.mkdir()
    (src / "app.ts").write_text("export function main() {}\n")
    (src / "utils.ts").write_text("export function helper() {}\n")

    # Root docs
    (repo / "README.md").write_text("# Test App\n")

    # Git init for history tests
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
         "commit", "-m", "initial commit"],
        cwd=str(repo), capture_output=True,
    )

    return repo


# ---------------------------------------------------------------------------
# Phase 2a: individual collectors
# ---------------------------------------------------------------------------

class TestCollectDirectoryTree:
    def test_returns_tree(self, fixture_repo):
        tree = _collect_directory_tree(fixture_repo)
        assert "src" in tree
        # .git directory itself excluded, but .github is fine
        lines = tree.splitlines()
        assert not any(line.rstrip("/") == "./.git" for line in lines)

    def test_nonexistent_dir(self, tmp_path):
        tree = _collect_directory_tree(tmp_path / "nonexistent")
        assert tree == ""


class TestCollectRootDocs:
    def test_finds_markdown(self, fixture_repo):
        docs = _collect_root_docs(fixture_repo)
        assert "README.md" in docs

    def test_finds_claude_md(self, fixture_repo):
        docs = _collect_root_docs(fixture_repo)
        assert "CLAUDE.md" in docs


class TestCollectProjectMetadata:
    def test_package_json(self, fixture_repo):
        meta = _collect_project_metadata(fixture_repo)
        assert "package_json" in meta
        assert meta["package_json"]["name"] == "test-app"
        assert "jest" in meta["package_json"]["devDependencies"]

    def test_pyproject_toml(self, tmp_path):
        repo = tmp_path / "pyrepo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "mypackage"\n\n[tool.pytest.ini_options]\n'
        )
        meta = _collect_project_metadata(repo)
        assert "pyproject_toml" in meta
        assert meta["pyproject_toml"]["name"] == "mypackage"

    def test_go_mod(self, tmp_path):
        repo = tmp_path / "gorepo"
        repo.mkdir()
        (repo / "go.mod").write_text("module github.com/org/mymod\n\ngo 1.21\n")
        meta = _collect_project_metadata(repo)
        assert "go_mod" in meta
        assert meta["go_mod"]["module"] == "github.com/org/mymod"

    def test_no_metadata_files(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        meta = _collect_project_metadata(repo)
        assert meta == {}


class TestCollectCiConfigs:
    def test_github_workflows(self, fixture_repo):
        ci = _collect_ci_configs(fixture_repo)
        assert ".github/workflows/ci.yml" in ci
        assert "name: CI" in ci[".github/workflows/ci.yml"]

    def test_dockerfile(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "Dockerfile").write_text("FROM node:18\n")
        ci = _collect_ci_configs(repo)
        assert "Dockerfile" in ci

    def test_blackbird_yaml(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "blackbird.yaml").write_text("version: 1\n")
        ci = _collect_ci_configs(repo)
        assert "blackbird.yaml" in ci

    def test_no_ci_files(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        ci = _collect_ci_configs(repo)
        assert ci == {}


class TestCollectTestInfrastructure:
    def test_detects_jest_config(self, fixture_repo):
        infra = _collect_test_infrastructure(fixture_repo)
        assert "jest.config.js" in infra["config_files"]

    def test_extracts_test_commands(self, fixture_repo):
        infra = _collect_test_infrastructure(fixture_repo)
        assert "test" in infra["commands"]
        assert infra["commands"]["test"] == "jest"
        assert "lint" in infra["commands"]

    def test_pyproject_pytest(self, tmp_path):
        repo = tmp_path / "pyrepo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-v'\n")
        infra = _collect_test_infrastructure(repo)
        assert "pyproject.toml [tool.pytest]" in infra["config_files"]

    def test_conftest_detected(self, tmp_path):
        repo = tmp_path / "pyrepo"
        repo.mkdir()
        (repo / "conftest.py").write_text("import pytest\n")
        infra = _collect_test_infrastructure(repo)
        assert "conftest.py" in infra["config_files"]


class TestCollectConventionFiles:
    def test_claude_md(self, fixture_repo):
        conventions = _collect_convention_files(fixture_repo)
        assert "CLAUDE.md" in conventions
        assert "Project Instructions" in conventions["CLAUDE.md"]

    def test_agents_md(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "AGENTS.md").write_text("# Agent Config\n")
        conventions = _collect_convention_files(repo)
        assert "AGENTS.md" in conventions

    def test_cursorrules(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".cursorrules").write_text("rules here\n")
        conventions = _collect_convention_files(repo)
        assert ".cursorrules" in conventions

    def test_project_level_claude_md(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        (repo / ".claude" / "CLAUDE.md").write_text("# Project level\n")
        conventions = _collect_convention_files(repo)
        assert ".claude/CLAUDE.md" in conventions


class TestCollectRecentGitHistory:
    def test_collects_commits(self, fixture_repo):
        commits, added = _collect_recent_git_history(str(fixture_repo))
        assert len(commits) >= 1
        assert "initial commit" in commits[0]

    def test_collects_added_files(self, fixture_repo):
        commits, added = _collect_recent_git_history(str(fixture_repo))
        # The initial commit added files
        assert len(added) >= 1

    def test_nonexistent_repo(self, tmp_path):
        commits, added = _collect_recent_git_history(str(tmp_path / "nope"))
        assert commits == []
        assert added == []


# ---------------------------------------------------------------------------
# Phase 2a: full prefetch_context
# ---------------------------------------------------------------------------

class TestPrefetchContext:
    def test_collects_all_sections(self, fixture_repo):
        bundle = prefetch_context(str(fixture_repo))
        assert bundle.repo_root == str(fixture_repo)
        assert bundle.directory_tree  # non-empty
        assert bundle.project_metadata  # has package.json
        assert bundle.ci_configs  # has workflow
        assert bundle.convention_files  # has CLAUDE.md
        assert bundle.recent_commits  # has git history

    def test_ci_config_always_present(self, fixture_repo):
        """CI config must always be in the bundle when files exist."""
        bundle = prefetch_context(str(fixture_repo))
        assert ".github/workflows/ci.yml" in bundle.ci_configs

    def test_with_ticket_keyword_search(self, fixture_repo):
        """Keywords from ticket should trigger codebase search."""
        # Create a file with a searchable keyword
        src = fixture_repo / "src"
        (src / "dark_mode.ts").write_text("export class DarkModeToggle {}\n")

        ticket = TicketFields(
            summary="Add DarkModeToggle to settings",
            acceptance_criteria=["DarkModeToggle renders correctly"],
        )
        bundle = prefetch_context(str(fixture_repo), ticket=ticket)
        # Keyword search should find the file
        assert any("dark_mode.ts" in f for f in bundle.keyword_matches)

    def test_without_ticket(self, fixture_repo):
        """Pre-fetch works without a ticket (no keyword search)."""
        bundle = prefetch_context(str(fixture_repo))
        assert bundle.keyword_matches == []

    def test_bundle_is_serializable(self, fixture_repo):
        """Bundle should be JSON-serializable for state persistence."""
        bundle = prefetch_context(str(fixture_repo))
        serialized = json.dumps(bundle.to_dict(), default=str)
        assert isinstance(serialized, str)
        data = json.loads(serialized)
        assert data["repo_root"] == str(fixture_repo)


# ---------------------------------------------------------------------------
# Phase 2b: exploration (dry-run only since SDK not available in tests)
# ---------------------------------------------------------------------------

class TestExploreDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_bundle(self, fixture_repo):
        from dark_factory.explore import explore_codebase

        bundle = prefetch_context(str(fixture_repo))
        ticket = TicketFields(summary="Add feature X")

        result = await explore_codebase(
            str(fixture_repo), bundle, ticket, dry_run=True,
        )
        assert result["status"] == "dry_run"
        assert "bundle" in result
        assert "ticket" in result
        assert result["bundle"]["repo_root"] == str(fixture_repo)
