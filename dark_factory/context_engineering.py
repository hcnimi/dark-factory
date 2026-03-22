"""Context engineering layers: import graph, test-source mapping, symbol extraction.

Extracted from explore.py to keep Phase 2a focused on the orchestration layer.
These three layers are deterministic (no LLM calls) and build structured context
from repo source files for injection into agent prompts.
"""

from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _read_file_safe(path: Path, *, max_bytes: int = 50_000) -> str:
    """Read a file, truncating if too large."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_bytes]
    except (OSError, UnicodeDecodeError):
        return ""


def _detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        return "python"
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        return "ts"
    elif ext == ".go":
        return "go"
    return ""


# ---------------------------------------------------------------------------
# Import graph: parsers, resolver, BFS traversal
# ---------------------------------------------------------------------------

# Regex patterns for import parsing
_PY_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.]+)"            # import foo.bar
    r"|^\s*from\s+([\w.]+)\s+import\b",  # from foo.bar import baz
    re.MULTILINE,
)

_TS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:(?:\{[^}]*\}|[\w*]+|\*\s+as\s+\w+)(?:\s*,\s*(?:\{[^}]*\}|[\w*]+|\*\s+as\s+\w+))*\s+from\s+)?['"]([^'"]+)['"])"""
    r"""|(?:require\s*\(\s*['"]([^'"]+)['"]\s*\))""",
    re.MULTILINE,
)

_GO_IMPORT_RE = re.compile(
    r'^\s*(?:import\s+(?:\w+\s+)?)?"([^"]+)"',
    re.MULTILINE,
)


def _parse_imports_python(content: str) -> list[str]:
    """Extract import targets from Python source."""
    results = []
    for m in _PY_IMPORT_RE.finditer(content):
        target = m.group(1) or m.group(2)
        if target:
            results.append(target)
    return results


def _parse_imports_ts(content: str) -> list[str]:
    """Extract import targets from TypeScript/JavaScript source."""
    results = []
    for m in _TS_IMPORT_RE.finditer(content):
        target = m.group(1) or m.group(2)
        if target:
            results.append(target)
    return results


def _parse_imports_go(content: str, go_mod_module: str = "") -> list[str]:
    """Extract import targets from Go source."""
    results = []
    for m in _GO_IMPORT_RE.finditer(content):
        target = m.group(1)
        if target:
            results.append(target)
    return results


def _resolve_import(
    import_str: str,
    source_file: str,
    repo_root: str,
    *,
    language: str = "",
) -> str | None:
    """Resolve an import string to a repo-relative file path.

    Returns None if the import cannot be resolved to a file within the repo.
    """
    root = Path(repo_root)

    if language == "python":
        return _resolve_python_import(import_str, source_file, root)
    elif language in ("typescript", "javascript", "ts", "js"):
        return _resolve_ts_import(import_str, source_file, root)
    elif language == "go":
        return _resolve_go_import(import_str, source_file, root)
    return None


def _resolve_python_import(
    import_str: str, source_file: str, root: Path
) -> str | None:
    """Resolve Python import to repo-relative path."""
    source_dir = str(Path(source_file).parent)

    if import_str.startswith("."):
        # Relative import: count leading dots for parent traversal
        dots = 0
        for ch in import_str:
            if ch == ".":
                dots += 1
            else:
                break
        remainder = import_str[dots:]

        # Navigate up from source directory (1 dot = same package, 2 = parent, etc.)
        base = Path(source_dir)
        for _ in range(dots - 1):
            base = base.parent

        if remainder:
            parts = remainder.split(".")
            candidate = base / "/".join(parts)
        else:
            candidate = base
    else:
        # Absolute import: convert dots to path separators
        parts = import_str.split(".")
        candidate = Path("/".join(parts))

    # Try as module file, then as package directory with __init__.py
    for test_path in (
        root / (str(candidate) + ".py"),
        root / str(candidate) / "__init__.py",
    ):
        if test_path.exists():
            return str(test_path.relative_to(root))

    return None


def _resolve_ts_import(
    import_str: str, source_file: str, root: Path
) -> str | None:
    """Resolve TypeScript/JS import to repo-relative path."""
    # Skip bare specifiers (npm packages) -- they don't start with . or /
    if not import_str.startswith((".")) and not import_str.startswith("/"):
        return None

    source_dir = Path(source_file).parent

    if import_str.startswith("."):
        base = source_dir / import_str
    else:
        # Absolute path from repo root (strip leading /)
        base = Path(import_str.lstrip("/"))

    # Extension variants to try
    extensions = [".ts", ".tsx", ".js", ".jsx"]
    index_variants = ["/index.ts", "/index.tsx", "/index.js", "/index.jsx"]

    # If the import already has an extension, try it directly
    if any(str(base).endswith(ext) for ext in extensions):
        candidate = root / base
        if candidate.exists():
            return str(candidate.relative_to(root))
        return None

    # Try adding extensions
    for ext in extensions:
        candidate = root / (str(base) + ext)
        if candidate.exists():
            return str(candidate.relative_to(root))

    # Try index file variants (for directory imports)
    for idx in index_variants:
        candidate = root / (str(base) + idx)
        if candidate.exists():
            return str(candidate.relative_to(root))

    return None


def _resolve_go_import(
    import_str: str, source_file: str, root: Path
) -> str | None:
    """Resolve Go import to repo-relative path using go.mod module path."""
    # Read go.mod to get module path
    go_mod_path = root / "go.mod"
    go_mod_module = ""
    if go_mod_path.exists():
        content = _read_file_safe(go_mod_path)
        for line in content.splitlines():
            if line.startswith("module "):
                go_mod_module = line.split(None, 1)[1].strip()
                break

    if not go_mod_module:
        return None

    # Strip module prefix to get repo-relative path
    if not import_str.startswith(go_mod_module):
        return None

    rel_path = import_str[len(go_mod_module):].lstrip("/")
    if not rel_path:
        rel_path = "."

    candidate_dir = root / rel_path
    if candidate_dir.is_dir():
        # Check for any .go files in the directory
        go_files = list(candidate_dir.glob("*.go"))
        if go_files:
            return rel_path

    return None


def _parse_imports_for_file(
    file_path: str, repo_root: str
) -> list[str]:
    """Parse imports from a file and resolve them to repo-relative paths."""
    root = Path(repo_root)
    full_path = root / file_path
    if not full_path.exists():
        return []

    content = _read_file_safe(full_path)
    if not content:
        return []

    language = _detect_language(file_path)
    if not language:
        return []

    # Parse raw import strings
    if language == "python":
        raw_imports = _parse_imports_python(content)
    elif language == "ts":
        raw_imports = _parse_imports_ts(content)
    elif language == "go":
        raw_imports = _parse_imports_go(content)
    else:
        return []

    # Resolve each import to a file path
    resolved = []
    for imp in raw_imports:
        result = _resolve_import(imp, file_path, repo_root, language=language)
        if result is not None:
            resolved.append(result)

    return resolved


def build_import_graph(
    seed_files: list[str], repo_root: str
) -> dict[str, list[str]]:
    """Build 2-hop import graph from seed files via BFS.

    Forward: A imports B (hop 1), B imports C (hop 2).
    Reverse: X imports A (where A is a seed file).
    Capped at 50 files total, prioritized by hop distance then alphabetical.
    """
    root = Path(repo_root)
    graph: dict[str, list[str]] = {}
    # Track hop distance for each discovered file
    distances: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()

    # Seed files are at distance 0
    for sf in seed_files:
        if (root / sf).exists():
            distances[sf] = 0
            queue.append((sf, 0))

    # BFS forward traversal to 2 hops
    while queue:
        current_file, depth = queue.popleft()

        if current_file in graph:
            continue

        imports = _parse_imports_for_file(current_file, repo_root)
        graph[current_file] = imports

        if depth < 2:
            for imp in imports:
                if imp not in distances:
                    distances[imp] = depth + 1
                    queue.append((imp, depth + 1))

    # Reverse edges: scan all supported files to find what imports seed files
    seed_set = set(seed_files)
    _add_reverse_imports(seed_set, graph, distances, root, repo_root)

    # Cap at 50 files, prioritized by hop distance then alphabetical
    if len(graph) > 50:
        # Sort files by (distance, alphabetical) and keep top 50
        all_files = sorted(graph.keys(), key=lambda f: (distances.get(f, 999), f))
        keep = set(all_files[:50])
        graph = {f: [imp for imp in imps if imp in keep]
                 for f, imps in graph.items() if f in keep}

    return graph


def _add_reverse_imports(
    seed_set: set[str],
    graph: dict[str, list[str]],
    distances: dict[str, int],
    root: Path,
    repo_root: str,
) -> None:
    """Find files that import any seed file and add them to the graph."""
    # Collect supported files in the repo (bounded scan)
    supported_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go"}
    candidates: list[str] = []

    for ext in supported_extensions:
        # Use glob to find files, cap at reasonable limit
        for p in root.rglob(f"*{ext}"):
            # Skip hidden dirs, node_modules, .venv
            parts = p.relative_to(root).parts
            if any(part.startswith(".") or part in ("node_modules", ".venv", "__pycache__")
                   for part in parts):
                continue
            rel = str(p.relative_to(root))
            if rel not in graph:
                candidates.append(rel)

    for candidate in candidates:
        imports = _parse_imports_for_file(candidate, repo_root)
        # Check if this file imports any seed file
        if any(imp in seed_set for imp in imports):
            if candidate not in distances:
                distances[candidate] = 1
            graph[candidate] = imports


def build_reverse_dependency_map(
    import_graph: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Build reverse lookup: for each file, which files import it.

    Used to generate 'Used by:' annotations in symbol context rendering.
    """
    reverse: dict[str, list[str]] = {}
    for source_file, imports in import_graph.items():
        for imported_file in imports:
            if imported_file not in reverse:
                reverse[imported_file] = []
            if source_file not in reverse[imported_file]:
                reverse[imported_file].append(source_file)
    # Sort each list for deterministic output
    for key in reverse:
        reverse[key].sort()
    return reverse


# ---------------------------------------------------------------------------
# Test-to-source mapping
# ---------------------------------------------------------------------------

# Patterns that identify test files across languages
_TEST_FILE_PATTERNS = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(?:test|spec)\.(?:ts|tsx|js|jsx)|[^/]+_test\.go)$"
)


def _is_test_file(file_path: str) -> bool:
    """Check if a file path looks like a test file."""
    return bool(_TEST_FILE_PATTERNS.search(file_path))


def _find_test_by_convention(source_path: str, repo_root: str) -> str | None:
    """Find test file for a source file using naming conventions.

    Checks language-specific patterns in order and returns the first match,
    or None if no convention-named test file exists on disk.
    """
    root = Path(repo_root)
    src = Path(source_path)
    name = src.stem
    suffix = src.suffix
    parent = str(src.parent)

    candidates: list[str] = []

    if suffix == ".py":
        # tests/test_{name}.py (flat)
        candidates.append(f"tests/test_{name}.py")
        # tests/{subdir}/test_{name}.py (mirror directory structure)
        if parent and parent != ".":
            candidates.append(f"tests/{parent}/test_{name}.py")
        # {name}_test.py (same directory)
        candidates.append(str(src.with_name(f"{name}_test.py")))
        # tests/{subdir}/{name}_test.py
        if parent and parent != ".":
            candidates.append(f"tests/{parent}/{name}_test.py")

    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        # {name}.test.{ext} (same directory)
        candidates.append(str(src.with_name(f"{name}.test{suffix}")))
        # {name}.spec.{ext} (same directory)
        candidates.append(str(src.with_name(f"{name}.spec{suffix}")))
        # Try .ts variants for .tsx files
        if suffix == ".tsx":
            candidates.append(str(src.with_name(f"{name}.test.tsx")))
            candidates.append(str(src.with_name(f"{name}.test.ts")))
        # __tests__/{name}.test.{ext}
        if parent and parent != ".":
            candidates.append(f"{parent}/__tests__/{name}.test{suffix}")
        else:
            candidates.append(f"__tests__/{name}.test{suffix}")

    elif suffix == ".go":
        # Go: {name}_test.go must be in the same directory
        candidates.append(str(src.with_name(f"{name}_test.go")))

    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate

    return None


def _find_test_by_import_scan(
    source_path: str, repo_root: str, test_files: list[str],
) -> str | None:
    """Fallback: scan test files for imports of the source module.

    Only checks files matching test naming patterns. Reads each test file
    and looks for import statements referencing the source.
    """
    root = Path(repo_root)
    src = Path(source_path)
    name = src.stem
    suffix = src.suffix

    # Build module names to search for in import statements
    search_terms: list[str] = []

    if suffix == ".py":
        # Python: from {module} import ... or import {module}
        # Convert path to dotted module: src/services/user.py -> src.services.user
        module_dotted = str(src.with_suffix("")).replace(os.sep, ".").replace("/", ".")
        search_terms.append(module_dotted)
        # Also match just the filename stem for relative imports
        search_terms.append(name)
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        # TS/JS: import ... from './path' or require('./path')
        search_terms.append(name)
        # Path without extension
        search_terms.append(str(src.with_suffix("")))
    elif suffix == ".go":
        # Go: package-level imports -- match by filename
        search_terms.append(name)

    for test_file in test_files:
        test_path = root / test_file
        if not test_path.is_file():
            continue
        try:
            content = test_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if suffix == ".py":
            for term in search_terms:
                # Match: from {module} import or import {module}
                if re.search(rf"\bfrom\s+{re.escape(term)}\b", content):
                    return test_file
                if re.search(rf"\bimport\s+{re.escape(term)}\b", content):
                    return test_file
        elif suffix in (".ts", ".tsx", ".js", ".jsx"):
            for term in search_terms:
                if term in content:
                    return test_file
        elif suffix == ".go":
            for term in search_terms:
                if term in content:
                    return test_file

    return None


def build_test_mapping(
    neighborhood_files: list[str], repo_root: str,
) -> dict[str, str | None]:
    """Build source-to-test mapping. Convention-first, import-scan fallback.

    Keys are source files only (test files excluded). Values are the
    repo-relative path to the matching test file, or None.
    """
    source_files = [f for f in neighborhood_files if not _is_test_file(f)]
    test_files = [f for f in neighborhood_files if _is_test_file(f)]

    mapping: dict[str, str | None] = {}
    unmatched: list[str] = []

    for src in source_files:
        test = _find_test_by_convention(src, repo_root)
        if test:
            mapping[src] = test
        else:
            unmatched.append(src)

    # Import-scan fallback for files not matched by convention
    for src in unmatched:
        test = _find_test_by_import_scan(src, repo_root, test_files)
        mapping[src] = test  # None if still unmatched

    return mapping


# ---------------------------------------------------------------------------
# Symbol extraction (regex-based, no AST)
# ---------------------------------------------------------------------------

# Matches Python __all__ = ["sym1", "sym2", ...] (single or multi-line)
_PYTHON_ALL_RE = re.compile(
    r"^__all__\s*=\s*\[([^\]]*)\]", re.MULTILINE | re.DOTALL
)


def _extract_symbols_python(content: str) -> list[str]:
    """Extract function/class/dataclass signatures from Python source."""
    symbols: list[str] = []

    # Detect __all__ exports for annotation
    all_exports: set[str] = set()
    all_match = _PYTHON_ALL_RE.search(content)
    if all_match:
        # Parse quoted names from the __all__ value
        all_exports = set(re.findall(r"""['"](\w+)['"]""", all_match.group(1)))

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip comments and empty lines
        if stripped.startswith("#") or not stripped:
            i += 1
            continue

        # Skip docstrings (triple-quoted blocks)
        if stripped.startswith(('"""', "'''")):
            quote = stripped[:3]
            # Single-line docstring
            if stripped.count(quote) >= 2:
                i += 1
                continue
            # Multi-line docstring: skip until closing quote
            i += 1
            while i < len(lines) and quote not in lines[i]:
                i += 1
            i += 1
            continue

        # Decorator detection: capture decorators for dataclass/staticmethod/classmethod
        decorators: list[str] = []
        while stripped.startswith("@"):
            decorators.append(stripped)
            i += 1
            if i < len(lines):
                line = lines[i]
                stripped = line.strip()
            else:
                break

        is_dataclass = any("dataclass" in d for d in decorators)
        decorator_prefix = ""
        for d in decorators:
            if "staticmethod" in d:
                decorator_prefix = "@staticmethod "
            elif "classmethod" in d:
                decorator_prefix = "@classmethod "

        # Function / async function
        func_match = re.match(
            r"^(\s*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)(\s*->\s*[^:]+)?:",
            line,
        )
        if func_match:
            indent = func_match.group(1)
            async_kw = (func_match.group(2) or "").strip()
            name = func_match.group(3)
            params = func_match.group(4).strip()
            ret = (func_match.group(5) or "").strip()
            prefix = f"{async_kw} " if async_kw else ""
            sig = f"{indent}{decorator_prefix}{prefix}def {name}({params}){ret}:"
            export_tag = " [exported]" if name in all_exports else ""
            symbols.append(sig + export_tag)
            i += 1
            continue

        # Class definition
        class_match = re.match(
            r"^(\s*)class\s+(\w+)([^:]*)?:", line,
        )
        if class_match:
            indent = class_match.group(1)
            name = class_match.group(2)
            bases = (class_match.group(3) or "").strip()
            sig = f"{indent}class {name}{bases}:"
            export_tag = " [exported]" if name in all_exports else ""
            symbols.append(sig + export_tag)

            # For dataclasses, extract field definitions
            if is_dataclass:
                j = i + 1
                while j < len(lines):
                    field_line = lines[j].strip()
                    if not field_line or field_line.startswith("#"):
                        j += 1
                        continue
                    if field_line.startswith(('"""', "'''")):
                        # Skip docstring
                        quote = field_line[:3]
                        if field_line.count(quote) >= 2:
                            j += 1
                            continue
                        j += 1
                        while j < len(lines) and quote not in lines[j]:
                            j += 1
                        j += 1
                        continue
                    # Field: name: Type [= default]
                    field_match = re.match(
                        r"^(\s+)(\w+)\s*:\s*(.+?)(\s*=.*)?$", lines[j],
                    )
                    if field_match:
                        symbols.append(lines[j].rstrip())
                        j += 1
                        continue
                    # Stop at methods or non-field lines
                    if field_line.startswith(("def ", "async def ", "class ", "@")):
                        break
                    # Other non-field content signals end of fields
                    break

            i += 1
            continue

        i += 1

    return symbols


def _extract_symbols_ts(content: str) -> list[str]:
    """Extract exported function/class/type/interface signatures from TypeScript."""
    symbols: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()

        # Only extract exported symbols
        if not stripped.startswith("export"):
            continue

        # export default
        if re.match(r"^export\s+default\s+", stripped):
            # Capture the full signature line
            sig = stripped.rstrip(";").rstrip("{").rstrip()
            symbols.append(sig)
            continue

        # export function / export async function
        func_match = re.match(
            r"^export\s+(async\s+)?function\s+(\w+)\s*(\([^)]*\))(\s*:\s*[^{;]+)?",
            stripped,
        )
        if func_match:
            async_kw = (func_match.group(1) or "").strip()
            name = func_match.group(2)
            params = func_match.group(3)
            ret = (func_match.group(4) or "").strip()
            prefix = f"async " if async_kw else ""
            sig = f"export {prefix}function {name}{params}"
            if ret:
                sig += f" {ret}"
            symbols.append(sig)
            continue

        # export class
        class_match = re.match(
            r"^export\s+class\s+(\w+)(\s+extends\s+\w+)?(\s+implements\s+[\w,\s]+)?",
            stripped,
        )
        if class_match:
            sig = class_match.group(0).rstrip("{").rstrip()
            symbols.append(sig)
            continue

        # export type
        type_match = re.match(
            r"^export\s+type\s+(\w+)\s*=\s*(.*)", stripped,
        )
        if type_match:
            name = type_match.group(1)
            value = type_match.group(2).rstrip(";").rstrip()
            symbols.append(f"export type {name} = {value}")
            continue

        # export interface
        iface_match = re.match(
            r"^export\s+interface\s+(\w+)(\s+extends\s+[\w,\s]+)?",
            stripped,
        )
        if iface_match:
            sig = iface_match.group(0).rstrip("{").rstrip()
            symbols.append(sig)
            continue

    return symbols


def _extract_symbols_go(content: str) -> list[str]:
    """Extract exported (capitalized) function/type signatures from Go."""
    symbols: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()

        # type Name struct/interface
        type_match = re.match(
            r"^type\s+([A-Z]\w*)\s+(struct|interface)\b", stripped,
        )
        if type_match:
            symbols.append(f"type {type_match.group(1)} {type_match.group(2)}")
            continue

        # type Name = ... (type alias)
        alias_match = re.match(
            r"^type\s+([A-Z]\w*)\s+=\s+(.*)", stripped,
        )
        if alias_match:
            symbols.append(
                f"type {alias_match.group(1)} = {alias_match.group(2).rstrip(';').rstrip()}"
            )
            continue

        # func (receiver) Name(params) return
        method_match = re.match(
            r"^func\s+\((\w+)\s+([*]?\w+)\)\s+([A-Z]\w*)\s*(\([^)]*\))(\s*[^{]*)?",
            stripped,
        )
        if method_match:
            recv_name = method_match.group(1)
            recv_type = method_match.group(2)
            name = method_match.group(3)
            params = method_match.group(4)
            ret = (method_match.group(5) or "").strip().rstrip("{").rstrip()
            sig = f"func ({recv_name} {recv_type}) {name}{params}"
            if ret:
                sig += f" {ret}"
            symbols.append(sig)
            continue

        # func Name(params) return -- only exported (capitalized)
        func_match = re.match(
            r"^func\s+([A-Z]\w*)\s*(\([^)]*\))(\s*[^{]*)?", stripped,
        )
        if func_match:
            name = func_match.group(1)
            params = func_match.group(2)
            ret = (func_match.group(3) or "").strip().rstrip("{").rstrip()
            sig = f"func {name}{params}"
            if ret:
                sig += f" {ret}"
            symbols.append(sig)
            continue

        # Skip unexported (lowercase) funcs/types -- they don't match the patterns above

    return symbols


def build_symbol_context(
    neighborhood_files: list[str],
    repo_root: str,
    import_graph: dict[str, list[str]] | None = None,
    seed_files: list[str] | None = None,
) -> dict[str, list[str]]:
    """Extract API surface from neighborhood files. Cap at 200 lines."""
    root = Path(repo_root)
    extractors = {
        ".py": _extract_symbols_python,
        ".ts": _extract_symbols_ts,
        ".tsx": _extract_symbols_ts,
        ".js": _extract_symbols_ts,
        ".jsx": _extract_symbols_ts,
        ".go": _extract_symbols_go,
    }

    # Determine hop distance for each file to prioritize closer files
    # hop 0 = seed files, hop 1 = direct imports of seeds, hop 2 = rest
    seed_set = set(seed_files) if seed_files else set()

    def _hop_distance(filepath: str) -> int:
        if not seed_set:
            return 0
        if filepath in seed_set:
            return 0
        # Check if any seed file imports this file (hop 1)
        if import_graph:
            for seed in seed_set:
                if filepath in import_graph.get(seed, []):
                    return 1
        return 2

    # Sort files by hop distance (closer first), then alphabetically for stability
    sorted_files = sorted(
        neighborhood_files,
        key=lambda f: (_hop_distance(f), f),
    )

    result: dict[str, list[str]] = {}
    total_lines = 0
    max_lines = 200

    for filepath in sorted_files:
        if total_lines >= max_lines:
            break

        ext = Path(filepath).suffix
        extractor = extractors.get(ext)
        if not extractor:
            continue

        full_path = root / filepath
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        symbols = extractor(content)
        if not symbols:
            continue

        # Enforce the 200-line cap: each file header is 1 line + N symbol lines
        lines_needed = 1 + len(symbols)
        remaining = max_lines - total_lines
        if lines_needed > remaining:
            # Truncate symbols to fit
            symbols = symbols[: max(0, remaining - 1)]
            if not symbols:
                break

        result[filepath] = symbols
        total_lines += 1 + len(symbols)

    return result
