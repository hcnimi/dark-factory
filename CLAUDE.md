<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

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

- `dark_factory/` — Python package (19 modules)
- `tests/` — Test suite (35 test files)

## Dependencies

No external Python dependencies. Requires `git` and `gh` CLI tools at runtime. Uses Claude Agent SDK for LLM calls (provided by the Claude Code environment).

## Principles

- Composition over inheritance
- Security first — parameterized queries, input validation
- Comments explain WHY not WHAT
