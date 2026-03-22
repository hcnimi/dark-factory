## Context

Phase 2a (`explore.py`) currently collects: directory tree, root docs, project metadata, CI configs, test infrastructure, convention files, recent git history, and keyword-matched files. Phase 2b passes this bundle to a Sonnet exploration agent with 15 turns and Read/Glob/Grep tools.

The keyword matching in `ingest.py` (`search_codebase_for_keywords`) uses `grep -rl` — it finds files that *mention* a term, not files that *depend on* each other. The exploration agent compensates by spending turns tracing relationships the deterministic layer could have provided.

All three new layers integrate into the existing `ContextBundle` dataclass and `prefetch_context()` flow. No new modules — everything lives in `explore.py` to keep the single-file simplicity of each pipeline phase.

## Goals / Non-Goals

**Goals:**
- Reduce Phase 2b turns from 15 → 3-5 by front-loading dependency/structure analysis
- Give Phase 7 implementer immediate awareness of test file locations and API surfaces
- Keep all three layers deterministic (no LLM calls, no new dependencies)
- Produce reusable artifacts (test mapping, import graph) consumed by later phases

**Non-Goals:**
- AST parsing or language-server integration (regex is sufficient for import/export patterns)
- Modifying Phase 7/8/9 to consume the new context (downstream work, separate change)
- Supporting languages beyond Python, TypeScript/JavaScript, and Go (cover the common cases first)
- Perfect accuracy — these are heuristics to improve LLM context, not compiler-grade analysis

## Decisions

### 1. Single file vs. new module

**Decision**: Add all three layers to `explore.py`.

**Rationale**: Each pipeline phase is currently one file. The three layers are all "deterministic context collection" — same responsibility as the existing Phase 2a code. Total addition is ~320 lines, keeping `explore.py` under 750 lines.

**Alternative considered**: New `context_engineering.py` module. Rejected because it fragments Phase 2a logic across files for no architectural benefit. If the file grows past ~800 lines, split then.

### 2. Regex-based parsing vs. tree-sitter / AST

**Decision**: Regex-based extraction for imports and symbols.

**Rationale**: Import statements are syntactically simple across Python/TS/Go. Regex handles the 95% case without adding a dependency. The output feeds an LLM that tolerates noise — false positives in import detection are harmless (slightly more context), while false negatives just mean the exploration agent does one extra Read.

**Alternative considered**: `tree-sitter` bindings for accurate parsing. Rejected because it adds a native dependency, complicates installation, and the marginal accuracy gain doesn't justify the cost for this use case.

### 3. Import graph depth

**Decision**: 2-hop neighborhood (file → imports → imports of imports).

**Rationale**: 1-hop misses indirect dependencies (e.g., `handler.py` → `service.py` → `repository.py`). 3-hop explodes in large codebases. 2-hop matches the typical "I need to understand the layer above and below" mental model.

**Implementation**: BFS from seed files (keyword matches) with a visited set. Cap output at 50 files to prevent context window bloat in monorepos.

### 4. Test-to-source mapping strategy

**Decision**: Convention-first with import-scan fallback.

**Rationale**: Most projects follow naming conventions (`src/X.ts` → `tests/X.test.ts`, `module/foo.py` → `tests/test_foo.py`). Convention matching is O(1) per file. Import scanning (read test file, extract imported modules, resolve to source) handles non-standard layouts but is more expensive. Try convention first, fall back to import scan for unmatched test files.

**Patterns to support**:
- Python: `test_*.py`, `*_test.py`, `tests/test_*.py`
- TypeScript/JS: `*.test.ts`, `*.spec.ts`, `__tests__/*.ts`
- Go: `*_test.go` (same directory, convention-enforced by language)

### 5. Symbol extraction scope

**Decision**: Extract only from files in the import graph's 2-hop neighborhood.

**Rationale**: Extracting symbols from the entire repo is wasteful. The import graph already identifies the relevant files. Extract signatures (function names, class names, type definitions, exports) from those ~6-50 files only.

**What to extract**:
- Python: `def`, `class`, `@dataclass` fields, `__all__`
- TypeScript: `export function`, `export class`, `export type/interface`, `export default`
- Go: Capitalized functions/types (exported by convention)

### 6. ContextBundle integration

**Decision**: Three new optional fields on `ContextBundle`, populated by `prefetch_context()`.

```python
import_graph: dict[str, list[str]]    # file → [imported files]
test_mapping: dict[str, str | None]   # source file → test file or None
symbol_context: dict[str, list[str]]  # file → [signatures]
```

`to_prompt_text()` renders these as new sections. Empty fields (no keyword matches → no seed files → no graph) produce no output.

## Risks / Trade-offs

**[Regex accuracy]** → Import patterns vary (dynamic imports, re-exports, barrel files). Mitigation: target the common patterns, accept that edge cases get caught by the exploration agent's remaining turns.

**[Context window bloat]** → Rich context could push the exploration prompt past useful size. Mitigation: cap import graph at 50 files, symbol context at 200 lines total, test mapping has natural size bounds.

**[Performance on large repos]** → Reading and parsing files in the 2-hop neighborhood. Mitigation: all I/O is already done for keyword matching; import graph adds at most ~100 file reads (each capped at 50KB). Total wall-clock: <2 seconds on typical repos.

**[Language coverage gaps]** → Only Python/TS/Go initially. Mitigation: regex patterns are easy to extend per-language. Unknown languages fall through to the existing keyword matching — no regression.

## Open Questions

1. Should the test-source mapping be persisted to `PipelineState` so Phase 7/8 can consume it without re-computing? (Likely yes, but that's downstream scope.)
2. Should symbol context include type annotations or just names? (Start with names + parameter types, iterate based on LLM usefulness.)
