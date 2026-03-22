## Why

Phase 2a collects repo structure, metadata, and keyword-matched files. Phase 2b gives Sonnet 15 turns to explore. But keyword matching finds files that *mention* something — not files that *depend on* something. The implementing agent in Phase 7 spends ~5 turns just orienting itself in code it's never seen. Top SWE-bench performers (Auggie at 51.8% vs raw SWE-Agent at 45.9%, same model) show that context engineering — not model capability — is the primary differentiator.

Three layers of deterministic context analysis can narrow the change neighborhood before the LLM ever runs, cutting Phase 2b from 15 to ~3 turns and saving ~30-40% of exploration tokens.

## What Changes

- **Import graph analysis**: Trace imports forward and reverse from keyword-matched files to find the 2-hop dependency neighborhood. Regex-based parsing per language, no AST required. Narrows 20 keyword-grep hits to ~6 files in the actual change neighborhood.
- **Test-to-source mapping**: Convention-based matching (`src/foo/bar.ts` → `tests/foo/bar.test.ts`) with import-scan fallback. Produces a `{source_file: test_file | None}` mapping consumed by Phase 7 (update tests), Phase 8 (targeted test runs), and Phase 9 (coverage check).
- **Symbol context extraction**: Regex-based extraction of function/class/type signatures from the change neighborhood — the "API surface" view. No function bodies, no comments. Gives the LLM a developer's mental model without reading entire files.
- **ContextBundle extension**: New fields on `ContextBundle` dataclass for the three layers. `to_prompt_text()` updated to render them.
- **Phase 2b turn reduction**: Exploration system prompt updated to reflect richer deterministic context. `max_turns` reduced from 15 to ~3-5.

## Capabilities

### New Capabilities
- `import-graph`: Trace import statements forward and reverse to build a 2-hop file dependency neighborhood from keyword-matched seed files
- `test-source-mapping`: Convention-based and import-scan mapping of source files to their test files, producing a reusable mapping dict
- `symbol-context`: Extract function/class/type signatures from files in the change neighborhood to produce an API surface view

### Modified Capabilities
<!-- No existing specs to modify — this is the first set -->

## Impact

- **`dark_factory/explore.py`**: Primary change target. New collection functions for each layer, extended `ContextBundle` dataclass, updated `to_prompt_text()`, updated `prefetch_context()` to call new collectors.
- **`dark_factory/explore.py` Phase 2b**: Updated system prompt template, reduced `max_turns`.
- **`dark_factory/pipeline.py`**: Phase 7 and Phase 8 can optionally consume the test-source mapping (downstream, not part of this change).
- **Dependencies**: None. All three layers are pure Python using `pathlib`, `re`, and subprocess for git. No new packages.
- **~320 lines** of new deterministic Python. Zero additional SDK calls.
