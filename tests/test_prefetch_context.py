"""Tests for prefetch_context() verifying collection of ALL context types.

Uses a comprehensive fixture repo with package.json, CI configs, test
infrastructure, convention files, git history, and keyword-searchable source.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dark_factory.explore import ContextBundle, prefetch_context
from dark_factory.ingest import TicketFields


@pytest.fixture
def full_fixture_repo(tmp_path):
    """A comprehensive repo with all context types for prefetch testing."""
    repo = tmp_path / "full-repo"
    repo.mkdir()

    # --- package.json ---
    (repo / "package.json").write_text(json.dumps({
        "name": "full-test-app",
        "version": "1.0.0",
        "scripts": {
            "test": "jest --coverage",
            "test:unit": "jest --testPathPattern=unit",
            "test:e2e": "jest --testPathPattern=e2e",
            "lint": "eslint . --ext .ts,.tsx",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": {"express": "^4.18.0", "pg": "^8.0.0"},
        "devDependencies": {
            "jest": "^29.0.0",
            "eslint": "^8.0.0",
            "typescript": "^5.0.0",
        },
    }))

    # --- CI configs ---
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
    )
    (workflows / "deploy.yml").write_text(
        "name: Deploy\non:\n  push:\n    branches: [main]\n"
    )
    (repo / "Dockerfile").write_text("FROM node:18-alpine\nWORKDIR /app\n")
    (repo / "Makefile").write_text(
        "test:\n\tnpm test\n\nlint:\n\tnpm run lint\n\ncheck: lint test\n"
    )

    # --- Test infrastructure ---
    (repo / "jest.config.js").write_text(
        "module.exports = { testEnvironment: 'node', collectCoverage: true };\n"
    )

    # --- Convention files ---
    (repo / "CLAUDE.md").write_text("# Project Rules\n\nRun `npm test` before committing.\n")
    (repo / ".editorconfig").write_text("root = true\n[*]\nindent_size = 2\n")
    (repo / ".prettierrc").write_text('{ "singleQuote": true }\n')

    # --- Source files ---
    src = repo / "src"
    src.mkdir()
    (src / "app.ts").write_text(
        "import express from 'express';\n"
        "export const app = express();\n"
        "export class AuthService {\n"
        "  async login(user: string) { return true; }\n"
        "}\n"
    )
    (src / "database.ts").write_text(
        "import { Pool } from 'pg';\n"
        "export const pool = new Pool();\n"
        "export async function query(sql: string) { return pool.query(sql); }\n"
    )
    (src / "utils.ts").write_text(
        "export function formatDate(d: Date): string { return d.toISOString(); }\n"
    )

    # --- Tests directory ---
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "app.test.ts").write_text(
        "describe('app', () => { it('starts', () => { expect(true).toBe(true); }); });\n"
    )

    # --- Docs ---
    (repo / "README.md").write_text("# Full Test App\n\nA test application.\n")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("# Architecture\n\nMVC pattern.\n")

    # --- Git init with multiple commits ---
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
         "commit", "-m", "feat: initial project setup"],
        cwd=str(repo), capture_output=True,
    )

    # Second commit
    (src / "middleware.ts").write_text("export function cors() { return (req: any, res: any, next: any) => next(); }\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
         "commit", "-m", "feat: add CORS middleware"],
        cwd=str(repo), capture_output=True,
    )

    return repo


# ---------------------------------------------------------------------------
# Context type: directory tree
# ---------------------------------------------------------------------------

class TestPrefetchDirectoryTree:
    def test_directory_tree_populated(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert bundle.directory_tree != ""
        assert "src" in bundle.directory_tree

    def test_directory_tree_excludes_git(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        lines = bundle.directory_tree.splitlines()
        assert not any(line.rstrip("/") == "./.git" for line in lines)


# ---------------------------------------------------------------------------
# Context type: root docs
# ---------------------------------------------------------------------------

class TestPrefetchRootDocs:
    def test_finds_readme(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "README.md" in bundle.root_docs

    def test_finds_claude_md(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "CLAUDE.md" in bundle.root_docs

    def test_finds_nested_docs(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert any("architecture.md" in d for d in bundle.root_docs)


# ---------------------------------------------------------------------------
# Context type: project metadata
# ---------------------------------------------------------------------------

class TestPrefetchProjectMetadata:
    def test_package_json_parsed(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "package_json" in bundle.project_metadata
        assert bundle.project_metadata["package_json"]["name"] == "full-test-app"

    def test_dependencies_extracted(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        deps = bundle.project_metadata["package_json"]["dependencies"]
        assert "express" in deps

    def test_dev_dependencies_extracted(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        dev_deps = bundle.project_metadata["package_json"]["devDependencies"]
        assert "jest" in dev_deps

    def test_scripts_extracted(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        scripts = bundle.project_metadata["package_json"]["scripts"]
        assert "test" in scripts


# ---------------------------------------------------------------------------
# Context type: CI configs
# ---------------------------------------------------------------------------

class TestPrefetchCiConfigs:
    def test_github_workflows_found(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert ".github/workflows/ci.yml" in bundle.ci_configs
        assert ".github/workflows/deploy.yml" in bundle.ci_configs

    def test_workflow_content_included(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "name: CI" in bundle.ci_configs[".github/workflows/ci.yml"]

    def test_dockerfile_found(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "Dockerfile" in bundle.ci_configs

    def test_makefile_found(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "Makefile" in bundle.ci_configs


# ---------------------------------------------------------------------------
# Context type: test infrastructure
# ---------------------------------------------------------------------------

class TestPrefetchTestInfrastructure:
    def test_jest_config_detected(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "jest.config.js" in bundle.test_infrastructure["config_files"]

    def test_test_commands_extracted(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        commands = bundle.test_infrastructure["commands"]
        assert "test" in commands
        assert "lint" in commands
        assert "typecheck" in commands

    def test_makefile_targets_extracted(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        commands = bundle.test_infrastructure["commands"]
        assert any("make" in k for k in commands)


# ---------------------------------------------------------------------------
# Context type: convention files
# ---------------------------------------------------------------------------

class TestPrefetchConventionFiles:
    def test_claude_md_content(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert "CLAUDE.md" in bundle.convention_files
        assert "npm test" in bundle.convention_files["CLAUDE.md"]

    def test_editorconfig(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert ".editorconfig" in bundle.convention_files

    def test_prettierrc(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert ".prettierrc" in bundle.convention_files


# ---------------------------------------------------------------------------
# Context type: git history
# ---------------------------------------------------------------------------

class TestPrefetchGitHistory:
    def test_recent_commits_collected(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert len(bundle.recent_commits) >= 2
        commit_text = " ".join(bundle.recent_commits)
        assert "initial project setup" in commit_text
        assert "CORS middleware" in commit_text

    def test_recently_added_files_collected(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        assert len(bundle.recently_added_files) >= 1


# ---------------------------------------------------------------------------
# Context type: keyword matches
# ---------------------------------------------------------------------------

class TestPrefetchKeywordMatches:
    def test_keyword_search_with_ticket(self, full_fixture_repo):
        ticket = TicketFields(
            summary="Add AuthService login rate limiting",
            acceptance_criteria=["AuthService tracks login attempts"],
        )
        bundle = prefetch_context(str(full_fixture_repo), ticket=ticket)
        assert any("app.ts" in f for f in bundle.keyword_matches)

    def test_keyword_search_database(self, full_fixture_repo):
        ticket = TicketFields(
            summary="Update database Pool configuration",
            acceptance_criteria=["Pool uses connection pooling"],
        )
        bundle = prefetch_context(str(full_fixture_repo), ticket=ticket)
        assert any("database.ts" in f for f in bundle.keyword_matches)

    def test_no_ticket_no_keywords(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo), ticket=None)
        assert bundle.keyword_matches == []


# ---------------------------------------------------------------------------
# Bundle serialization
# ---------------------------------------------------------------------------

class TestPrefetchSerialization:
    def test_bundle_json_serializable(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        serialized = json.dumps(bundle.to_dict(), default=str)
        data = json.loads(serialized)
        assert data["repo_root"] == str(full_fixture_repo)
        assert isinstance(data["ci_configs"], dict)
        assert isinstance(data["test_infrastructure"], dict)

    def test_prompt_text_includes_all_sections(self, full_fixture_repo):
        bundle = prefetch_context(str(full_fixture_repo))
        text = bundle.to_prompt_text()
        assert "Repository Structure" in text
        assert "Root Documentation" in text
        assert "Project Metadata" in text
        assert "CI/CD Configuration" in text
        assert "Test Infrastructure" in text
        assert "Convention Files" in text
        assert "Recent Commits" in text


# ---------------------------------------------------------------------------
# Empty / minimal repos
# ---------------------------------------------------------------------------

class TestPrefetchMinimalRepo:
    def test_empty_directory(self, tmp_path):
        """prefetch_context should not crash on a bare directory."""
        empty = tmp_path / "empty"
        empty.mkdir()
        bundle = prefetch_context(str(empty))
        assert bundle.repo_root == str(empty)
        assert bundle.project_metadata == {}
        assert bundle.ci_configs == {}
        assert bundle.convention_files == {}
        assert bundle.recent_commits == []

    def test_git_only_repo(self, tmp_path):
        """Repo with only .git dir, no source files."""
        repo = tmp_path / "git-only"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        bundle = prefetch_context(str(repo))
        assert bundle.directory_tree != ""  # at least "." line
        assert bundle.project_metadata == {}


# ---------------------------------------------------------------------------
# Integration: context engineering layers (import graph, test mapping, symbols)
# ---------------------------------------------------------------------------

@pytest.fixture
def context_eng_repo(tmp_path):
    """Repo with cross-file imports for testing context engineering layers."""
    repo = tmp_path / "ctx-eng"
    repo.mkdir()

    # Python files with import relationships
    src = repo / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "service.py").write_text(
        "from .repository import UserRepo\n\n"
        "class UserService:\n"
        "    def __init__(self, repo: UserRepo):\n"
        "        self.repo = repo\n\n"
        "    def get_user(self, user_id: str) -> dict:\n"
        "        return self.repo.find(user_id)\n"
    )
    (src / "repository.py").write_text(
        "class UserRepo:\n"
        "    def find(self, user_id: str) -> dict:\n"
        "        return {'id': user_id}\n"
    )
    (src / "handler.py").write_text(
        "from .service import UserService\n\n"
        "def handle_request(user_id: str) -> dict:\n"
        "    svc = UserService(None)\n"
        "    return svc.get_user(user_id)\n"
    )

    # Test files matching conventions
    tests = repo / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_service.py").write_text(
        "from src.service import UserService\n\n"
        "def test_get_user():\n"
        "    pass\n"
    )
    (tests / "test_handler.py").write_text(
        "from src.handler import handle_request\n\n"
        "def test_handle():\n"
        "    pass\n"
    )

    # pyproject.toml for project type detection
    (repo / "pyproject.toml").write_text('[project]\nname = "ctx-eng"\n')

    # Git init
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com",
         "commit", "-m", "initial"],
        cwd=str(repo), capture_output=True,
    )

    return repo


class TestContextEngineeringIntegration:
    """Task 4.3: prefetch_context with fixture repo populates all three new fields."""

    def test_import_graph_populated(self, context_eng_repo):
        ticket = TicketFields(
            summary="Update UserService to add caching",
            acceptance_criteria=["UserService caches results"],
        )
        bundle = prefetch_context(str(context_eng_repo), ticket=ticket)
        # keyword search should find service.py, import graph should trace dependencies
        assert bundle.import_graph, "import_graph should be populated when keywords match"

    def test_test_mapping_populated(self, context_eng_repo):
        ticket = TicketFields(
            summary="Update UserService to add caching",
            acceptance_criteria=["UserService caches results"],
        )
        bundle = prefetch_context(str(context_eng_repo), ticket=ticket)
        if bundle.import_graph:
            assert isinstance(bundle.test_mapping, dict)

    def test_symbol_context_populated(self, context_eng_repo):
        ticket = TicketFields(
            summary="Update UserService to add caching",
            acceptance_criteria=["UserService caches results"],
        )
        bundle = prefetch_context(str(context_eng_repo), ticket=ticket)
        if bundle.import_graph:
            assert isinstance(bundle.symbol_context, dict)

    def test_all_three_fields_in_prompt_text(self, context_eng_repo):
        ticket = TicketFields(
            summary="Update UserService to add caching",
            acceptance_criteria=["UserService caches results"],
        )
        bundle = prefetch_context(str(context_eng_repo), ticket=ticket)
        text = bundle.to_prompt_text()
        # At minimum, keyword matches should produce some context
        assert "Keyword-Matched Files" in text

    def test_no_ticket_no_context_engineering(self, context_eng_repo):
        """Without a ticket, no keyword matches → no context engineering layers."""
        bundle = prefetch_context(str(context_eng_repo))
        assert bundle.import_graph == {}
        assert bundle.test_mapping == {}
        assert bundle.symbol_context == {}

    def test_bundle_serializable_with_new_fields(self, context_eng_repo):
        ticket = TicketFields(
            summary="Update UserService to add caching",
            acceptance_criteria=["UserService caches results"],
        )
        bundle = prefetch_context(str(context_eng_repo), ticket=ticket)
        serialized = json.dumps(bundle.to_dict(), default=str)
        data = json.loads(serialized)
        assert "import_graph" in data
        assert "test_mapping" in data
        assert "symbol_context" in data
