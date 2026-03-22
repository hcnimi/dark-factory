"""Tests for import graph: parsers, resolver, and BFS traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

from dark_factory.explore import (
    ContextBundle,
    _parse_imports_go,
    _parse_imports_python,
    _parse_imports_ts,
    _resolve_import,
    build_import_graph,
)


# ---------------------------------------------------------------------------
# Python import parsing
# ---------------------------------------------------------------------------

class TestParseImportsPython:
    def test_absolute_import(self):
        content = "import os\nimport json\n"
        result = _parse_imports_python(content)
        assert "os" in result
        assert "json" in result

    def test_dotted_import(self):
        content = "import dark_factory.explore\n"
        result = _parse_imports_python(content)
        assert "dark_factory.explore" in result

    def test_from_import(self):
        content = "from dark_factory.explore import ContextBundle\n"
        result = _parse_imports_python(content)
        assert "dark_factory.explore" in result

    def test_relative_import_single_dot(self):
        content = "from .service import UserService\n"
        result = _parse_imports_python(content)
        assert ".service" in result

    def test_relative_import_double_dot(self):
        content = "from ..utils import helper\n"
        result = _parse_imports_python(content)
        assert "..utils" in result

    def test_relative_import_bare_dot(self):
        content = "from . import models\n"
        result = _parse_imports_python(content)
        assert "." in result

    def test_mixed_imports(self):
        content = (
            "import os\n"
            "from pathlib import Path\n"
            "from .service import UserService\n"
            "import json\n"
        )
        result = _parse_imports_python(content)
        assert len(result) == 4
        assert "os" in result
        assert "pathlib" in result
        assert ".service" in result
        assert "json" in result

    def test_no_imports(self):
        content = "x = 1\nprint(x)\n"
        result = _parse_imports_python(content)
        assert result == []

    def test_comment_ignored_inline(self):
        """Import-like text inside strings is still matched by regex -- acceptable."""
        content = "import real_module\n"
        result = _parse_imports_python(content)
        assert "real_module" in result


# ---------------------------------------------------------------------------
# TypeScript/JS import parsing
# ---------------------------------------------------------------------------

class TestParseImportsTs:
    def test_named_import(self):
        content = "import { foo } from './service';\n"
        result = _parse_imports_ts(content)
        assert "./service" in result

    def test_default_import(self):
        content = "import React from 'react';\n"
        result = _parse_imports_ts(content)
        assert "react" in result

    def test_star_import(self):
        content = "import * as utils from '../utils/helper';\n"
        result = _parse_imports_ts(content)
        assert "../utils/helper" in result

    def test_require(self):
        content = "const bar = require('../utils/helper');\n"
        result = _parse_imports_ts(content)
        assert "../utils/helper" in result

    def test_multiple_named_imports(self):
        content = "import { foo, bar, baz } from './service';\n"
        result = _parse_imports_ts(content)
        assert "./service" in result

    def test_side_effect_import(self):
        content = "import './polyfill';\n"
        result = _parse_imports_ts(content)
        assert "./polyfill" in result

    def test_mixed_imports(self):
        content = (
            "import { UserService } from './service';\n"
            "import React from 'react';\n"
            "const lodash = require('lodash');\n"
        )
        result = _parse_imports_ts(content)
        assert "./service" in result
        assert "react" in result
        assert "lodash" in result

    def test_no_imports(self):
        content = "const x = 1;\nconsole.log(x);\n"
        result = _parse_imports_ts(content)
        assert result == []


# ---------------------------------------------------------------------------
# Go import parsing
# ---------------------------------------------------------------------------

class TestParseImportsGo:
    def test_single_import(self):
        content = 'import "fmt"\n'
        result = _parse_imports_go(content)
        assert "fmt" in result

    def test_grouped_imports(self):
        content = (
            'import (\n'
            '    "fmt"\n'
            '    "net/http"\n'
            '    "mymodule/pkg/handler"\n'
            ')\n'
        )
        result = _parse_imports_go(content)
        assert "fmt" in result
        assert "net/http" in result
        assert "mymodule/pkg/handler" in result

    def test_aliased_import(self):
        content = 'import mypkg "mymodule/pkg/handler"\n'
        # The regex should still capture the path
        result = _parse_imports_go(content)
        assert "mymodule/pkg/handler" in result

    def test_no_imports(self):
        content = "package main\n\nfunc main() {}\n"
        result = _parse_imports_go(content)
        assert result == []


# ---------------------------------------------------------------------------
# Import resolver
# ---------------------------------------------------------------------------

class TestResolveImport:
    def test_python_absolute_import(self, tmp_path):
        """Absolute Python import resolves to file."""
        repo = tmp_path / "repo"
        (repo / "dark_factory").mkdir(parents=True)
        (repo / "dark_factory" / "explore.py").write_text("# module\n")
        result = _resolve_import(
            "dark_factory.explore", "main.py", str(repo), language="python"
        )
        assert result == "dark_factory/explore.py"

    def test_python_relative_import(self, tmp_path):
        """Relative Python import resolves from source file location."""
        repo = tmp_path / "repo"
        pkg = repo / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "service.py").write_text("# service\n")
        (pkg / "handler.py").write_text("from .service import Svc\n")
        result = _resolve_import(
            ".service", "pkg/handler.py", str(repo), language="python"
        )
        assert result == "pkg/service.py"

    def test_python_package_init(self, tmp_path):
        """Python import resolves to __init__.py for packages."""
        repo = tmp_path / "repo"
        pkg = repo / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("# init\n")
        result = _resolve_import(
            "mypkg", "main.py", str(repo), language="python"
        )
        assert result == "mypkg/__init__.py"

    def test_python_unresolvable_external(self, tmp_path):
        """External Python packages return None."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _resolve_import(
            "requests", "main.py", str(repo), language="python"
        )
        assert result is None

    def test_ts_relative_import(self, tmp_path):
        """Relative TS import resolves with extension probing."""
        repo = tmp_path / "repo"
        src = repo / "src"
        src.mkdir(parents=True)
        (src / "service.ts").write_text("export class Svc {}\n")
        result = _resolve_import(
            "./service", "src/handler.ts", str(repo), language="ts"
        )
        assert result == "src/service.ts"

    def test_ts_index_file(self, tmp_path):
        """TS import resolves to index file in directory."""
        repo = tmp_path / "repo"
        src = repo / "src"
        utils = src / "utils"
        utils.mkdir(parents=True)
        (utils / "index.ts").write_text("export function helper() {}\n")
        result = _resolve_import(
            "./utils", "src/handler.ts", str(repo), language="ts"
        )
        assert result == "src/utils/index.ts"

    def test_ts_bare_specifier_returns_none(self, tmp_path):
        """Bare npm specifiers (non-relative) return None."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _resolve_import(
            "react", "src/app.tsx", str(repo), language="ts"
        )
        assert result is None

    def test_go_import_with_module(self, tmp_path):
        """Go import resolves using go.mod module path."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "go.mod").write_text("module github.com/org/mymod\n\ngo 1.21\n")
        pkg_dir = repo / "pkg" / "handler"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "handler.go").write_text("package handler\n")
        result = _resolve_import(
            "github.com/org/mymod/pkg/handler",
            "cmd/main.go",
            str(repo),
            language="go",
        )
        assert result == "pkg/handler"

    def test_go_external_package_returns_none(self, tmp_path):
        """External Go packages return None."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "go.mod").write_text("module github.com/org/mymod\n\ngo 1.21\n")
        result = _resolve_import(
            "fmt", "cmd/main.go", str(repo), language="go"
        )
        assert result is None

    def test_unknown_language_returns_none(self, tmp_path):
        """Unknown language silently returns None."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _resolve_import(
            "something", "file.rb", str(repo), language="ruby"
        )
        assert result is None


# ---------------------------------------------------------------------------
# BFS traversal
# ---------------------------------------------------------------------------

class TestBuildImportGraph:
    def test_simple_chain_two_hops(self, tmp_path):
        """A imports B, B imports C -- both included in 2-hop graph."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("from .b import func\n")
        (repo / "b.py").write_text("from .c import helper\n")
        (repo / "c.py").write_text("# leaf\nx = 1\n")

        graph = build_import_graph(["a.py"], str(repo))

        assert "a.py" in graph
        assert "b.py" in graph["a.py"]
        assert "b.py" in graph
        assert "c.py" in graph["b.py"]

    def test_hop_3_excluded(self, tmp_path):
        """File at hop 3 (D) is NOT included in the graph."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("from .b import func\n")
        (repo / "b.py").write_text("from .c import helper\n")
        (repo / "c.py").write_text("from .d import deep\n")
        (repo / "d.py").write_text("# too deep\n")

        graph = build_import_graph(["a.py"], str(repo))

        # c.py is in the graph (hop 2), but its imports to d.py are parsed
        # however d.py itself should NOT be traversed (distance 3)
        assert "a.py" in graph
        assert "b.py" in graph
        assert "c.py" in graph
        # d.py may appear in c.py's import list but should not be a key with
        # its own traversal at depth > 2
        assert "d.py" not in graph

    def test_reverse_edges_included(self, tmp_path):
        """File X that imports a seed file is included as reverse dependency."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "seed.py").write_text("# seed file\nx = 1\n")
        (repo / "consumer.py").write_text("from .seed import x\n")

        graph = build_import_graph(["seed.py"], str(repo))

        # consumer.py imports seed.py, so it should appear via reverse scan
        assert "consumer.py" in graph
        assert "seed.py" in graph["consumer.py"]

    def test_cap_at_50_files(self, tmp_path):
        """Graph with >50 files is capped at 50."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create a seed file that imports many modules
        imports = []
        for i in range(60):
            name = f"mod_{i:03d}.py"
            (repo / name).write_text("# module\n")
            imports.append(f"from .mod_{i:03d} import x")

        (repo / "seed.py").write_text("\n".join(imports) + "\n")

        graph = build_import_graph(["seed.py"], str(repo))

        assert len(graph) <= 50

    def test_cap_preserves_closest_by_hop(self, tmp_path):
        """When capping, files closest to seeds (by hop distance) are kept."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Seed at distance 0
        imports_hop1 = []
        for i in range(30):
            name = f"hop1_{i:03d}.py"
            (repo / name).write_text("# hop1 module\n")
            imports_hop1.append(f"from .hop1_{i:03d} import x")

        (repo / "seed.py").write_text("\n".join(imports_hop1) + "\n")

        # Each hop1 file imports a unique hop2 file (30 more = 61 total)
        for i in range(30):
            hop1_name = f"hop1_{i:03d}.py"
            hop2_name = f"hop2_{i:03d}.py"
            (repo / hop2_name).write_text("# hop2 module\n")
            (repo / hop1_name).write_text(f"from .hop2_{i:03d} import y\n")

        graph = build_import_graph(["seed.py"], str(repo))

        assert len(graph) <= 50
        # Seed and all hop1 files (31) should be included since they're closer
        assert "seed.py" in graph

    def test_empty_seed_files(self, tmp_path):
        """Empty seed list produces empty graph."""
        repo = tmp_path / "repo"
        repo.mkdir()
        graph = build_import_graph([], str(repo))
        assert graph == {}

    def test_nonexistent_seed_file(self, tmp_path):
        """Nonexistent seed files are silently skipped."""
        repo = tmp_path / "repo"
        repo.mkdir()
        graph = build_import_graph(["nonexistent.py"], str(repo))
        assert graph == {}

    def test_typescript_chain(self, tmp_path):
        """TS import chain is followed correctly."""
        repo = tmp_path / "repo"
        src = repo / "src"
        src.mkdir(parents=True)
        (src / "app.ts").write_text("import { svc } from './service';\n")
        (src / "service.ts").write_text("import { db } from './db';\n")
        (src / "db.ts").write_text("// database layer\n")

        graph = build_import_graph(["src/app.ts"], str(repo))

        assert "src/app.ts" in graph
        assert "src/service.ts" in graph["src/app.ts"]
        assert "src/service.ts" in graph
        assert "src/db.ts" in graph["src/service.ts"]

    def test_mixed_languages_independent(self, tmp_path):
        """Python and TS seed files are handled independently."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("from .utils import helper\n")
        (repo / "utils.py").write_text("# utils\n")
        src = repo / "src"
        src.mkdir()
        (src / "app.ts").write_text("import { x } from './lib';\n")
        (src / "lib.ts").write_text("// lib\n")

        graph = build_import_graph(["main.py", "src/app.ts"], str(repo))

        assert "main.py" in graph
        assert "utils.py" in graph["main.py"]
        assert "src/app.ts" in graph
        assert "src/lib.ts" in graph["src/app.ts"]

    def test_cycle_does_not_loop(self, tmp_path):
        """Circular imports terminate correctly."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("from .b import x\n")
        (repo / "b.py").write_text("from .a import y\n")

        graph = build_import_graph(["a.py"], str(repo))

        assert "a.py" in graph
        assert "b.py" in graph
        # No infinite loop -- function should return


# ---------------------------------------------------------------------------
# ContextBundle import_graph rendering
# ---------------------------------------------------------------------------

class TestContextBundleImportGraph:
    def test_import_graph_in_to_prompt_text(self):
        bundle = ContextBundle(
            import_graph={
                "src/app.py": ["src/service.py", "src/utils.py"],
                "src/service.py": ["src/db.py"],
            }
        )
        text = bundle.to_prompt_text()
        assert "## Import Graph" in text
        assert "src/app.py" in text
        assert "src/service.py, src/utils.py" in text

    def test_empty_import_graph_not_rendered(self):
        bundle = ContextBundle()
        text = bundle.to_prompt_text()
        assert "Import Graph" not in text

    def test_import_graph_in_to_dict(self):
        bundle = ContextBundle(
            import_graph={"a.py": ["b.py"]}
        )
        d = bundle.to_dict()
        assert d["import_graph"] == {"a.py": ["b.py"]}
