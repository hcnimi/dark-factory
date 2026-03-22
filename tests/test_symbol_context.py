"""Tests for symbol context extraction and build_symbol_context."""

from __future__ import annotations

from pathlib import Path

import pytest

from dark_factory.explore import (
    _extract_symbols_go,
    _extract_symbols_python,
    _extract_symbols_ts,
    build_symbol_context,
)


# ---------------------------------------------------------------------------
# Python symbol extraction
# ---------------------------------------------------------------------------


class TestExtractSymbolsPython:
    def test_extracts_def(self):
        content = "def get_user(user_id: str) -> User:\n    return db.find(user_id)\n"
        symbols = _extract_symbols_python(content)
        assert any("def get_user" in s for s in symbols)
        assert any("-> User" in s for s in symbols)

    def test_extracts_class(self):
        content = "class UserService:\n    pass\n"
        symbols = _extract_symbols_python(content)
        assert any("class UserService" in s for s in symbols)

    def test_extracts_async_def(self):
        content = "async def fetch_data(url: str) -> dict:\n    return await get(url)\n"
        symbols = _extract_symbols_python(content)
        assert any("async" in s and "def fetch_data" in s for s in symbols)

    def test_extracts_dataclass_fields(self):
        content = (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Config:\n"
            "    host: str\n"
            "    port: int = 8080\n"
            "    debug: bool = False\n"
        )
        symbols = _extract_symbols_python(content)
        assert any("class Config" in s for s in symbols)
        assert any("host: str" in s for s in symbols)
        assert any("port: int" in s for s in symbols)
        assert any("debug: bool" in s for s in symbols)

    def test_all_exports_annotated(self):
        content = (
            '__all__ = ["UserService", "get_user"]\n\n'
            "class UserService:\n    pass\n\n"
            "def get_user(uid: str) -> User:\n    pass\n\n"
            "def _internal_helper():\n    pass\n"
        )
        symbols = _extract_symbols_python(content)
        # Exported symbols should be tagged
        user_svc = [s for s in symbols if "UserService" in s]
        assert user_svc and "[exported]" in user_svc[0]

        get_user = [s for s in symbols if "get_user" in s]
        assert get_user and "[exported]" in get_user[0]

        # Non-exported should NOT be tagged
        helper = [s for s in symbols if "_internal_helper" in s]
        assert helper and "[exported]" not in helper[0]

    def test_function_bodies_excluded(self):
        content = (
            "def process(data: list[str]) -> int:\n"
            "    total = 0\n"
            "    for item in data:\n"
            "        total += len(item)\n"
            "    return total\n"
        )
        symbols = _extract_symbols_python(content)
        assert len(symbols) == 1
        assert "def process" in symbols[0]
        # Body lines must not appear
        assert not any("total = 0" in s for s in symbols)
        assert not any("for item" in s for s in symbols)

    def test_staticmethod_classmethod(self):
        content = (
            "class MyClass:\n"
            "    @staticmethod\n"
            "    def static_method(x: int) -> int:\n"
            "        return x\n"
            "\n"
            "    @classmethod\n"
            "    def class_method(cls, y: str) -> str:\n"
            "        return y\n"
        )
        symbols = _extract_symbols_python(content)
        static = [s for s in symbols if "static_method" in s]
        assert static and "@staticmethod" in static[0]

        classm = [s for s in symbols if "class_method" in s]
        assert classm and "@classmethod" in classm[0]

    def test_skips_comments_and_docstrings(self):
        content = (
            '"""Module docstring."""\n\n'
            "# A comment\n"
            "def real_func() -> None:\n"
            '    """Function docstring."""\n'
            "    pass\n"
        )
        symbols = _extract_symbols_python(content)
        assert len(symbols) == 1
        assert "real_func" in symbols[0]

    def test_multiline_all(self):
        content = (
            "__all__ = [\n"
            '    "Alpha",\n'
            '    "Beta",\n'
            "]\n\n"
            "class Alpha:\n    pass\n\n"
            "class Beta:\n    pass\n\n"
            "class Gamma:\n    pass\n"
        )
        symbols = _extract_symbols_python(content)
        alpha = [s for s in symbols if "Alpha" in s]
        assert alpha and "[exported]" in alpha[0]
        beta = [s for s in symbols if "Beta" in s]
        assert beta and "[exported]" in beta[0]
        gamma = [s for s in symbols if "Gamma" in s]
        assert gamma and "[exported]" not in gamma[0]


# ---------------------------------------------------------------------------
# TypeScript symbol extraction
# ---------------------------------------------------------------------------


class TestExtractSymbolsTs:
    def test_export_function(self):
        content = "export function createUser(data: CreateUserInput): Promise<User> {\n  return db.create(data);\n}\n"
        symbols = _extract_symbols_ts(content)
        assert len(symbols) == 1
        assert "export" in symbols[0]
        assert "createUser" in symbols[0]

    def test_export_async_function(self):
        content = "export async function fetchData(url: string): Promise<Response> {\n  return fetch(url);\n}\n"
        symbols = _extract_symbols_ts(content)
        assert any("async" in s and "fetchData" in s for s in symbols)

    def test_export_class(self):
        content = "export class UserService extends BaseService {\n  constructor() { super(); }\n}\n"
        symbols = _extract_symbols_ts(content)
        assert any("export class UserService" in s for s in symbols)
        assert any("extends BaseService" in s for s in symbols)

    def test_export_type(self):
        content = "export type Status = 'active' | 'inactive';\n"
        symbols = _extract_symbols_ts(content)
        assert any("export type Status" in s for s in symbols)

    def test_export_interface(self):
        content = "export interface UserResponse {\n  id: string;\n  name: string;\n}\n"
        symbols = _extract_symbols_ts(content)
        assert any("export interface UserResponse" in s for s in symbols)

    def test_export_default(self):
        content = "export default class App {\n}\n"
        symbols = _extract_symbols_ts(content)
        assert any("export default" in s for s in symbols)

    def test_non_exported_symbols_skipped(self):
        content = (
            "function internalHelper(x: number): number {\n  return x * 2;\n}\n\n"
            "class InternalClass {\n}\n\n"
            "interface InternalInterface {\n  x: number;\n}\n\n"
            "type InternalType = string;\n\n"
            "export function publicFunc(): void {}\n"
        )
        symbols = _extract_symbols_ts(content)
        assert len(symbols) == 1
        assert "publicFunc" in symbols[0]
        assert not any("internalHelper" in s for s in symbols)
        assert not any("InternalClass" in s for s in symbols)
        assert not any("InternalInterface" in s for s in symbols)
        assert not any("InternalType" in s for s in symbols)

    def test_multiple_exports(self):
        content = (
            "export function alpha(): void {}\n"
            "export class Beta {}\n"
            "export type Gamma = string;\n"
            "export interface Delta {}\n"
        )
        symbols = _extract_symbols_ts(content)
        assert len(symbols) == 4


# ---------------------------------------------------------------------------
# Go symbol extraction
# ---------------------------------------------------------------------------


class TestExtractSymbolsGo:
    def test_exported_function(self):
        content = "func HandleRequest(w http.ResponseWriter, r *http.Request) {\n}\n"
        symbols = _extract_symbols_go(content)
        assert any("HandleRequest" in s for s in symbols)

    def test_unexported_function_skipped(self):
        content = (
            "func handleInternal(w http.ResponseWriter) {\n}\n\n"
            "func helper() error {\n  return nil\n}\n"
        )
        symbols = _extract_symbols_go(content)
        assert len(symbols) == 0

    def test_receiver_method(self):
        content = "func (s *Server) HandleRequest(w http.ResponseWriter, r *http.Request) error {\n}\n"
        symbols = _extract_symbols_go(content)
        assert len(symbols) == 1
        assert "(s *Server)" in symbols[0]
        assert "HandleRequest" in symbols[0]

    def test_unexported_receiver_method_skipped(self):
        content = "func (s *Server) handleInternal() {\n}\n"
        symbols = _extract_symbols_go(content)
        assert len(symbols) == 0

    def test_exported_type_struct(self):
        content = "type Config struct {\n  Host string\n  Port int\n}\n"
        symbols = _extract_symbols_go(content)
        assert any("type Config struct" in s for s in symbols)

    def test_exported_type_interface(self):
        content = "type Repository interface {\n  Find(id string) (*Entity, error)\n}\n"
        symbols = _extract_symbols_go(content)
        assert any("type Repository interface" in s for s in symbols)

    def test_unexported_type_skipped(self):
        content = "type internalConfig struct {\n  host string\n}\n"
        symbols = _extract_symbols_go(content)
        assert len(symbols) == 0

    def test_mixed_exported_and_unexported(self):
        content = (
            "func PublicFunc() string {\n  return \"\"\n}\n\n"
            "func privateFunc() int {\n  return 0\n}\n\n"
            "type PublicType struct {}\n\n"
            "type privateType struct {}\n\n"
            "func (r *Repo) GetAll() []Item {\n  return nil\n}\n\n"
            "func (r *Repo) getOne() *Item {\n  return nil\n}\n"
        )
        symbols = _extract_symbols_go(content)
        names = " ".join(symbols)
        assert "PublicFunc" in names
        assert "PublicType" in names
        assert "GetAll" in names
        assert "privateFunc" not in names
        assert "privateType" not in names
        assert "getOne" not in names

    def test_function_with_return_type(self):
        content = "func NewServer(addr string) *Server {\n  return &Server{addr: addr}\n}\n"
        symbols = _extract_symbols_go(content)
        assert any("NewServer" in s and "*Server" in s for s in symbols)


# ---------------------------------------------------------------------------
# build_symbol_context
# ---------------------------------------------------------------------------


class TestBuildSymbolContext:
    def test_basic_extraction(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def hello() -> str:\n    return 'hi'\n")

        result = build_symbol_context(
            neighborhood_files=["app.py"],
            repo_root=str(tmp_path),
        )
        assert "app.py" in result
        assert any("def hello" in s for s in result["app.py"])

    def test_cap_enforcement(self, tmp_path):
        """Files generating >200 total lines get truncated."""
        # Create many Python files, each with several functions
        files = []
        for i in range(30):
            f = tmp_path / f"mod{i}.py"
            funcs = "\n\n".join(
                f"def func_{j}(x: int) -> int:\n    return x\n"
                for j in range(10)
            )
            f.write_text(funcs)
            files.append(f"mod{i}.py")

        result = build_symbol_context(
            neighborhood_files=files,
            repo_root=str(tmp_path),
        )
        # Count total lines: 1 header per file + N symbols
        total = sum(1 + len(sigs) for sigs in result.values())
        assert total <= 200

    def test_hop_distance_prioritization(self, tmp_path):
        """Seed files (hop 0) should appear before hop-2 files when cap is tight."""
        seed_file = tmp_path / "seed.py"
        seed_file.write_text(
            "\n\n".join(f"def seed_func_{i}() -> None:\n    pass\n" for i in range(80))
        )

        hop1_file = tmp_path / "hop1.py"
        hop1_file.write_text(
            "\n\n".join(f"def hop1_func_{i}() -> None:\n    pass\n" for i in range(80))
        )

        hop2_file = tmp_path / "hop2.py"
        hop2_file.write_text(
            "\n\n".join(f"def hop2_func_{i}() -> None:\n    pass\n" for i in range(80))
        )

        # import_graph: seed imports hop1, hop1 imports hop2
        import_graph = {
            "seed.py": ["hop1.py"],
            "hop1.py": ["hop2.py"],
        }

        result = build_symbol_context(
            neighborhood_files=["seed.py", "hop1.py", "hop2.py"],
            repo_root=str(tmp_path),
            import_graph=import_graph,
            seed_files=["seed.py"],
        )

        # seed.py should be included (hop 0)
        assert "seed.py" in result

        # With 200-line cap and seed having 80 funcs (81 lines incl header),
        # hop1 gets 80 funcs (81 lines), which is 162 total; hop2 might be
        # partially included or excluded
        keys = list(result.keys())
        # Seed file should be first due to hop 0 priority
        assert keys[0] == "seed.py"

    def test_unsupported_extension_skipped(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Hello\n")

        result = build_symbol_context(
            neighborhood_files=["readme.md"],
            repo_root=str(tmp_path),
        )
        assert result == {}

    def test_missing_file_skipped(self, tmp_path):
        result = build_symbol_context(
            neighborhood_files=["nonexistent.py"],
            repo_root=str(tmp_path),
        )
        assert result == {}

    def test_empty_file_skipped(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")

        result = build_symbol_context(
            neighborhood_files=["empty.py"],
            repo_root=str(tmp_path),
        )
        assert result == {}

    def test_multi_language(self, tmp_path):
        py = tmp_path / "service.py"
        py.write_text("class Service:\n    pass\n")

        ts = tmp_path / "client.ts"
        ts.write_text("export function connect(): void {}\n")

        go = tmp_path / "handler.go"
        go.write_text("func HandleRequest() error {\n  return nil\n}\n")

        result = build_symbol_context(
            neighborhood_files=["service.py", "client.ts", "handler.go"],
            repo_root=str(tmp_path),
        )
        assert "service.py" in result
        assert "client.ts" in result
        assert "handler.go" in result

    def test_no_seed_files_all_equal_priority(self, tmp_path):
        """When seed_files is not provided, all files treated equally."""
        for name in ["a.py", "b.py", "c.py"]:
            (tmp_path / name).write_text(f"def {name[0]}_func() -> None:\n    pass\n")

        result = build_symbol_context(
            neighborhood_files=["c.py", "a.py", "b.py"],
            repo_root=str(tmp_path),
        )
        # All files should be sorted alphabetically (stable sort, all hop 0)
        keys = list(result.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# ContextBundle integration
# ---------------------------------------------------------------------------


class TestContextBundleSymbolContext:
    def test_symbol_context_field_default(self):
        from dark_factory.explore import ContextBundle
        b = ContextBundle()
        assert b.symbol_context == {}

    def test_to_prompt_text_renders_api_surface(self):
        from dark_factory.explore import ContextBundle
        b = ContextBundle(
            symbol_context={
                "src/service.py": ["class Service:", "  def get(self) -> dict:"],
                "src/utils.py": ["def helper() -> str:"],
            },
        )
        text = b.to_prompt_text()
        assert "API Surface (Symbol Context)" in text
        assert "── src/service.py ──" in text
        assert "  class Service:" in text
        assert "── src/utils.py ──" in text

    def test_to_prompt_text_no_symbol_context(self):
        from dark_factory.explore import ContextBundle
        b = ContextBundle()
        text = b.to_prompt_text()
        assert "API Surface" not in text

    def test_to_dict_includes_symbol_context(self):
        from dark_factory.explore import ContextBundle
        b = ContextBundle(
            symbol_context={"file.py": ["def foo():"]},
        )
        d = b.to_dict()
        assert "symbol_context" in d
        assert d["symbol_context"] == {"file.py": ["def foo():"]}
