## 1. Import Graph

- [x] 1.1 Add regex-based import parsers for Python, TypeScript/JS, and Go (`_parse_imports_python`, `_parse_imports_ts`, `_parse_imports_go`)
- [x] 1.2 Add import-to-file-path resolver (`_resolve_import`) that maps import strings to repo-relative file paths, trying extension variants for TS/JS
- [x] 1.3 Implement `build_import_graph(seed_files, repo_root)` — BFS to 2 hops with forward and reverse edges, capped at 50 files
- [x] 1.4 Add `import_graph` field to `ContextBundle` dataclass and render in `to_prompt_text()`
- [x] 1.5 Write tests for import parsing (Python relative/absolute, TS import/require, Go, unresolvable externals)
- [x] 1.6 Write tests for BFS traversal (2-hop limit, cap at 50, reverse edges)

## 2. Test-to-Source Mapping

- [x] 2.1 Implement `_find_test_by_convention(source_path, repo_root)` with Python/TS/Go naming patterns
- [x] 2.2 Implement `_find_test_by_import_scan(source_path, repo_root)` — scan test files for imports of the source module
- [x] 2.3 Implement `build_test_mapping(neighborhood_files, repo_root)` — convention-first, import-scan fallback, scoped to neighborhood
- [x] 2.4 Add `test_mapping` field to `ContextBundle` and render in `to_prompt_text()`
- [x] 2.5 Write tests for convention matching (all patterns per language, no-match → None)
- [x] 2.6 Write tests for import-scan fallback (test file imports source, scope limited to test-named files)

## 3. Symbol Context

- [x] 3.1 Implement `_extract_symbols_python(content)` — def, class, dataclass fields, `__all__` exports
- [x] 3.2 Implement `_extract_symbols_ts(content)` — export function/class/type/interface
- [x] 3.3 Implement `_extract_symbols_go(content)` — exported (capitalized) funcs/types, skip unexported
- [x] 3.4 Implement `build_symbol_context(neighborhood_files, repo_root, import_graph)` — extract from neighborhood, cap at 200 lines, prioritize by hop distance
- [x] 3.5 Add `symbol_context` field to `ContextBundle` and render as API surface view with `Used by:` annotations in `to_prompt_text()`
- [x] 3.6 Write tests for symbol extraction (each language, body exclusion, export annotation)
- [x] 3.7 Write tests for cap enforcement and hop-distance prioritization

## 4. Integration

- [x] 4.1 Wire all three layers into `prefetch_context()` — call after keyword matching, pass seed files to import graph, pass neighborhood to test mapping and symbol context
- [x] 4.2 Update Phase 2b exploration system prompt to reference new context sections and reduce `max_turns` from 15 to 5
- [x] 4.3 Write integration test: `prefetch_context()` with a fixture repo produces populated `ContextBundle` with all three new fields
- [x] 4.4 Run full test suite, verify no regressions in existing Phase 2a/2b behavior
