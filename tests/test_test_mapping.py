"""Tests for test-to-source mapping layer in dark_factory.explore."""

from __future__ import annotations

from pathlib import Path

import pytest

from dark_factory.explore import (
    ContextBundle,
    _find_test_by_convention,
    _find_test_by_import_scan,
    _is_test_file,
    build_test_mapping,
)


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

class TestIsTestFile:
    def test_python_test_prefix(self):
        assert _is_test_file("tests/test_user.py") is True

    def test_python_test_suffix(self):
        assert _is_test_file("src/user_test.py") is True

    def test_typescript_test(self):
        assert _is_test_file("src/Button.test.ts") is True

    def test_typescript_spec(self):
        assert _is_test_file("src/Button.spec.ts") is True

    def test_tsx_test(self):
        assert _is_test_file("src/Button.test.tsx") is True

    def test_go_test(self):
        assert _is_test_file("pkg/handler_test.go") is True

    def test_regular_python_file(self):
        assert _is_test_file("src/services/user.py") is False

    def test_regular_ts_file(self):
        assert _is_test_file("src/Button.tsx") is False

    def test_regular_go_file(self):
        assert _is_test_file("pkg/handler.go") is False

    def test_conftest_not_test(self):
        assert _is_test_file("tests/conftest.py") is False

    def test_js_test(self):
        assert _is_test_file("src/utils.test.js") is True

    def test_js_spec(self):
        assert _is_test_file("src/utils.spec.js") is True


# ---------------------------------------------------------------------------
# _find_test_by_convention: Python
# ---------------------------------------------------------------------------

class TestFindTestByConventionPython:
    def test_finds_tests_dir_test_prefix(self, tmp_path):
        """src/services/user.py -> tests/test_user.py"""
        (tmp_path / "src" / "services").mkdir(parents=True)
        (tmp_path / "src" / "services" / "user.py").write_text("class User: pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_user.py").write_text("def test_user(): pass\n")

        result = _find_test_by_convention("src/services/user.py", str(tmp_path))
        assert result == "tests/test_user.py"

    def test_finds_tests_subdir_test_prefix(self, tmp_path):
        """src/services/user.py -> tests/src/services/test_user.py"""
        (tmp_path / "src" / "services").mkdir(parents=True)
        (tmp_path / "src" / "services" / "user.py").write_text("class User: pass\n")
        (tmp_path / "tests" / "src" / "services").mkdir(parents=True)
        (tmp_path / "tests" / "src" / "services" / "test_user.py").write_text(
            "def test_user(): pass\n"
        )

        result = _find_test_by_convention("src/services/user.py", str(tmp_path))
        # Flat tests/ dir doesn't exist, so subdir match wins
        assert result == "tests/src/services/test_user.py"

    def test_finds_suffix_convention(self, tmp_path):
        """src/foo.py -> src/foo_test.py"""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").write_text("def foo(): pass\n")
        (tmp_path / "src" / "foo_test.py").write_text("def test_foo(): pass\n")

        result = _find_test_by_convention("src/foo.py", str(tmp_path))
        assert result == "src/foo_test.py"

    def test_finds_suffix_convention_mirrored_directory(self, tmp_path):
        """src/services/user.py -> tests/services/user_test.py (mirrored dir)"""
        (tmp_path / "src" / "services").mkdir(parents=True)
        (tmp_path / "src" / "services" / "user.py").write_text("class User: pass\n")
        (tmp_path / "tests" / "src" / "services").mkdir(parents=True)
        (tmp_path / "tests" / "src" / "services" / "user_test.py").write_text(
            "def test_user(): pass\n"
        )

        result = _find_test_by_convention("src/services/user.py", str(tmp_path))
        assert result == "tests/src/services/user_test.py"

    def test_returns_first_match(self, tmp_path):
        """When multiple conventions match, return the first."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bar.py").write_text("def bar(): pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_bar.py").write_text("def test_bar(): pass\n")
        (tmp_path / "src" / "bar_test.py").write_text("def test_bar(): pass\n")

        result = _find_test_by_convention("src/bar.py", str(tmp_path))
        # tests/test_bar.py is checked first
        assert result == "tests/test_bar.py"

    def test_no_match_returns_none(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "orphan.py").write_text("x = 1\n")

        result = _find_test_by_convention("src/orphan.py", str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# _find_test_by_convention: TypeScript
# ---------------------------------------------------------------------------

class TestFindTestByConventionTypeScript:
    def test_finds_test_ts(self, tmp_path):
        """src/Button.tsx -> src/Button.test.tsx"""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Button.tsx").write_text("export const Button = () => {}\n")
        (tmp_path / "src" / "Button.test.tsx").write_text("test('Button', () => {})\n")

        result = _find_test_by_convention("src/Button.tsx", str(tmp_path))
        assert result == "src/Button.test.tsx"

    def test_finds_spec_ts(self, tmp_path):
        """src/utils.ts -> src/utils.spec.ts"""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.ts").write_text("export function helper() {}\n")
        (tmp_path / "src" / "utils.spec.ts").write_text("test('helper', () => {})\n")

        result = _find_test_by_convention("src/utils.ts", str(tmp_path))
        assert result == "src/utils.spec.ts"

    def test_finds_dunder_tests_dir(self, tmp_path):
        """src/Card.ts -> src/__tests__/Card.test.ts"""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Card.ts").write_text("export class Card {}\n")
        (tmp_path / "src" / "__tests__").mkdir()
        (tmp_path / "src" / "__tests__" / "Card.test.ts").write_text(
            "test('Card', () => {})\n"
        )

        result = _find_test_by_convention("src/Card.ts", str(tmp_path))
        assert result == "src/__tests__/Card.test.ts"

    def test_no_match_returns_none(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "lonely.ts").write_text("export const x = 1\n")

        result = _find_test_by_convention("src/lonely.ts", str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# _find_test_by_convention: Go
# ---------------------------------------------------------------------------

class TestFindTestByConventionGo:
    def test_finds_test_go(self, tmp_path):
        """pkg/handler.go -> pkg/handler_test.go"""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "handler.go").write_text("package pkg\nfunc Handle() {}\n")
        (tmp_path / "pkg" / "handler_test.go").write_text(
            "package pkg\nfunc TestHandle(t *testing.T) {}\n"
        )

        result = _find_test_by_convention("pkg/handler.go", str(tmp_path))
        assert result == "pkg/handler_test.go"

    def test_no_match_returns_none(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "server.go").write_text("package pkg\n")

        result = _find_test_by_convention("pkg/server.go", str(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# _find_test_by_import_scan
# ---------------------------------------------------------------------------

class TestFindTestByImportScan:
    def test_python_from_import(self, tmp_path):
        """Test file imports source module via 'from X import Y'."""
        (tmp_path / "src" / "services").mkdir(parents=True)
        (tmp_path / "src" / "services" / "auth.py").write_text("def login(): pass\n")
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_auth.py"
        test_file.write_text(
            "from src.services.auth import login\n\ndef test_login(): pass\n"
        )

        result = _find_test_by_import_scan(
            "src/services/auth.py",
            str(tmp_path),
            ["tests/test_auth.py"],
        )
        assert result == "tests/test_auth.py"

    def test_python_import_statement(self, tmp_path):
        """Test file imports source module via 'import X'."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.py").write_text("def helper(): pass\n")
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_helpers.py"
        test_file.write_text("import src.utils\n\ndef test_helper(): pass\n")

        result = _find_test_by_import_scan(
            "src/utils.py",
            str(tmp_path),
            ["tests/test_helpers.py"],
        )
        assert result == "tests/test_helpers.py"

    def test_no_import_match(self, tmp_path):
        """Test file doesn't import the source -> None."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "secret.py").write_text("x = 42\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_other.py").write_text(
            "from src.other import something\n"
        )

        result = _find_test_by_import_scan(
            "src/secret.py",
            str(tmp_path),
            ["tests/test_other.py"],
        )
        assert result is None

    def test_typescript_import(self, tmp_path):
        """TS test file imports source via path string."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "api.ts").write_text("export function fetchData() {}\n")
        (tmp_path / "src" / "api.test.ts").write_text(
            "import { fetchData } from './api'\n\ntest('fetch', () => {})\n"
        )

        result = _find_test_by_import_scan(
            "src/api.ts",
            str(tmp_path),
            ["src/api.test.ts"],
        )
        assert result == "src/api.test.ts"

    def test_only_scans_provided_test_files(self, tmp_path):
        """Import scan only reads the test_files list, not arbitrary files."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "core.py").write_text("def main(): pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_core.py").write_text("from src.core import main\n")
        # A non-test file that also imports core -- should not be returned
        (tmp_path / "src" / "runner.py").write_text("from src.core import main\n")

        result = _find_test_by_import_scan(
            "src/core.py",
            str(tmp_path),
            ["tests/test_core.py"],  # only this file is scanned
        )
        assert result == "tests/test_core.py"

    def test_nonexistent_test_file_skipped(self, tmp_path):
        """Missing test file paths are silently skipped."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "x.py").write_text("y = 1\n")

        result = _find_test_by_import_scan(
            "src/x.py",
            str(tmp_path),
            ["tests/test_ghost.py"],
        )
        assert result is None


# ---------------------------------------------------------------------------
# build_test_mapping
# ---------------------------------------------------------------------------

class TestBuildTestMapping:
    def test_excludes_test_files_from_keys(self, tmp_path):
        """Test files should not appear as keys in the mapping."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def run(): pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test_run(): pass\n")

        mapping = build_test_mapping(
            ["src/app.py", "tests/test_app.py"],
            str(tmp_path),
        )
        assert "src/app.py" in mapping
        assert "tests/test_app.py" not in mapping

    def test_convention_match(self, tmp_path):
        """Convention matching is used first."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "model.py").write_text("class Model: pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_model.py").write_text("def test_model(): pass\n")

        mapping = build_test_mapping(
            ["src/model.py", "tests/test_model.py"],
            str(tmp_path),
        )
        assert mapping["src/model.py"] == "tests/test_model.py"

    def test_import_scan_fallback(self, tmp_path):
        """When convention fails, import scan is used as fallback."""
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "helper.py").write_text("def assist(): pass\n")
        (tmp_path / "checks").mkdir()
        # Non-standard directory, but test-named file
        (tmp_path / "checks" / "test_helpers.py").write_text(
            "from lib.helper import assist\n\ndef test_assist(): pass\n"
        )

        mapping = build_test_mapping(
            ["lib/helper.py", "checks/test_helpers.py"],
            str(tmp_path),
        )
        # Convention won't match (no tests/test_helper.py), but import scan will
        assert mapping["lib/helper.py"] == "checks/test_helpers.py"

    def test_no_match_returns_none(self, tmp_path):
        """Source with no matching test -> None."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "lonely.py").write_text("x = 1\n")

        mapping = build_test_mapping(["src/lonely.py"], str(tmp_path))
        assert mapping["src/lonely.py"] is None

    def test_mixed_languages(self, tmp_path):
        """Handles multiple languages in the same neighborhood."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def run(): pass\n")
        (tmp_path / "src" / "Button.tsx").write_text("export const Button = () => {}\n")
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "handler.go").write_text("package pkg\n")

        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test_run(): pass\n")
        (tmp_path / "src" / "Button.test.tsx").write_text("test('Button', () => {})\n")
        (tmp_path / "pkg" / "handler_test.go").write_text("package pkg\n")

        files = [
            "src/app.py", "src/Button.tsx", "pkg/handler.go",
            "tests/test_app.py", "src/Button.test.tsx", "pkg/handler_test.go",
        ]
        mapping = build_test_mapping(files, str(tmp_path))

        assert mapping["src/app.py"] == "tests/test_app.py"
        assert mapping["src/Button.tsx"] == "src/Button.test.tsx"
        assert mapping["pkg/handler.go"] == "pkg/handler_test.go"
        # Test files not in keys
        assert "tests/test_app.py" not in mapping
        assert "src/Button.test.tsx" not in mapping
        assert "pkg/handler_test.go" not in mapping


# ---------------------------------------------------------------------------
# ContextBundle integration
# ---------------------------------------------------------------------------

class TestContextBundleTestMapping:
    def test_test_mapping_field_default(self):
        bundle = ContextBundle()
        assert bundle.test_mapping == {}

    def test_to_prompt_text_includes_mapping(self):
        bundle = ContextBundle(
            test_mapping={
                "src/app.py": "tests/test_app.py",
                "src/orphan.py": None,
            },
        )
        text = bundle.to_prompt_text()
        assert "Test-Source Mapping" in text
        assert "src/app.py" in text
        assert "tests/test_app.py" in text
        assert "(no test found)" in text

    def test_to_prompt_text_empty_mapping_omitted(self):
        bundle = ContextBundle()
        text = bundle.to_prompt_text()
        assert "Test-Source Mapping" not in text

    def test_to_dict_includes_mapping(self):
        bundle = ContextBundle(
            test_mapping={"a.py": "test_a.py", "b.py": None},
        )
        d = bundle.to_dict()
        assert d["test_mapping"] == {"a.py": "test_a.py", "b.py": None}
