# dark-factory

Deterministic Python pipeline for autonomous spec-to-PR orchestration. Takes a Jira ticket, spec file, or inline description and produces a ready-to-review pull request.

## Development

**Run tests:**
```bash
python3 -m pytest tests/
```

**Run the pipeline:**
```bash
python3 -m dark_factory run <jira-key|file|description> [--dry-run] [--resume]
```

**Install (editable):**
```bash
pip install -e .
```

**Initialize in a target repo:**
```bash
cd /path/to/your/repo
dark-factory init
```

## Structure

- `dark_factory/` — Python package (17 modules)
- `tests/` — Test suite (32 test files)

## Dependencies

No external Python dependencies. Requires `git` and `gh` CLI tools at runtime. Uses Claude Agent SDK for LLM calls (provided by the Claude Code environment).

## Principles

- Composition over inheritance
- Security first — parameterized queries, input validation
- Comments explain WHY not WHAT
