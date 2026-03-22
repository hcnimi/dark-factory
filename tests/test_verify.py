"""Tests for dark_factory.verify: Phase 10 local dev verification."""

from __future__ import annotations

import json

import pytest

from dark_factory.verify import (
    DevServerInfo,
    detect_dev_command,
    render_verification_checklist,
    start_dev_server,
)


class TestDetectDevCommand:
    def test_detects_from_claude_md(self, tmp_path):
        claude_md = "Run the dev server with `npm run dev` on port 3000."
        info = detect_dev_command(str(tmp_path), claude_md)
        assert info.command == "npm run dev"
        assert info.detected_from == "CLAUDE.md"

    def test_detects_yarn_dev(self, tmp_path):
        claude_md = "Start: yarn dev"
        info = detect_dev_command(str(tmp_path), claude_md)
        assert info.command == "yarn dev"

    def test_detects_python_uvicorn(self, tmp_path):
        claude_md = "Dev: python3 -m uvicorn app:main --reload"
        info = detect_dev_command(str(tmp_path), claude_md)
        assert info.command == "python3 -m uvicorn"

    def test_detects_url_from_claude_md(self, tmp_path):
        claude_md = "Server runs at http://localhost:8080"
        info = detect_dev_command(str(tmp_path), claude_md)
        assert info.url == "http://localhost:8080"

    def test_fallback_to_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"dev": "next dev"}})
        )
        info = detect_dev_command(str(tmp_path))
        assert info.command == "npm run dev"
        assert "package.json" in info.detected_from

    def test_fallback_to_makefile(self, tmp_path):
        (tmp_path / "Makefile").write_text("dev:\n\tgo run .")
        info = detect_dev_command(str(tmp_path))
        assert info.command == "make dev"
        assert info.detected_from == "Makefile"

    def test_no_command_found(self, tmp_path):
        info = detect_dev_command(str(tmp_path))
        assert info.command is None

    def test_default_url(self, tmp_path):
        info = detect_dev_command(str(tmp_path))
        assert info.url == "http://localhost:3000"

    def test_detects_port_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"dev": "next dev --port 4000"}})
        )
        info = detect_dev_command(str(tmp_path))
        assert info.url == "http://localhost:4000"

    def test_claude_md_takes_priority(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"dev": "next dev"}})
        )
        claude_md = "Use `yarn dev` to start."
        info = detect_dev_command(str(tmp_path), claude_md)
        assert info.command == "yarn dev"
        assert info.detected_from == "CLAUDE.md"


class TestRenderVerificationChecklist:
    def test_contains_command(self):
        info = DevServerInfo(command="npm run dev", url="http://localhost:3000", detected_from="CLAUDE.md")
        output = render_verification_checklist(info, "/tmp/wt", ["Check the UI"])
        assert "npm run dev" in output
        assert "http://localhost:3000" in output

    def test_contains_check_items(self):
        info = DevServerInfo(command="npm run dev", url="http://localhost:3000", detected_from="CLAUDE.md")
        output = render_verification_checklist(info, "/tmp/wt", ["Check login", "Check dashboard"])
        assert "Check login" in output
        assert "Check dashboard" in output

    def test_no_command_shows_skip_message(self):
        info = DevServerInfo()
        output = render_verification_checklist(info, "/tmp/wt", [])
        assert "No dev server command detected" in output
        assert "Skipping" in output

    def test_contains_worktree_path(self):
        info = DevServerInfo(command="make dev", url="http://localhost:8080", detected_from="Makefile")
        output = render_verification_checklist(info, "/my/worktree", [])
        assert "/my/worktree" in output


class TestStartDevServer:
    def test_dry_run_returns_none(self):
        result = start_dev_server("/tmp", "npm run dev", dry_run=True)
        assert result is None
