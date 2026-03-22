"""Phase 1: Jira/file/inline ingestion.

Extracts structured ticket fields from the input source.  Jira and file
ingestion are deterministic; inline uses an SDK interview call.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TicketFields:
    """Structured fields extracted from any input source."""

    summary: str = ""
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    raw_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def searchable_text(self) -> str:
        """Combine summary and acceptance criteria for keyword extraction."""
        parts = [self.summary]
        parts.extend(self.acceptance_criteria)
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Jira ingestion (Phase 1, deterministic field extraction)
# ---------------------------------------------------------------------------

# Jira REST response fields we care about
_JIRA_FIELD_MAP = {
    "summary": "summary",
    "description": "description",
    "labels": "labels",
    "components": "components",
}

# Acceptance criteria often lives in a custom field or in the description
# under a heading like "Acceptance Criteria" or "AC"
_AC_HEADING_RE = re.compile(
    r"(?:^|\n)#+\s*(?:acceptance\s+criteria|ac)\s*\n(.*?)(?=\n#|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _extract_ac_from_description(description: str) -> list[str]:
    """Pull acceptance criteria bullet points from a Jira description."""
    match = _AC_HEADING_RE.search(description)
    if not match:
        return []
    block = match.group(1).strip()
    # Parse bullet points (-, *, or numbered)
    criteria = []
    for line in block.splitlines():
        stripped = re.sub(r"^\s*[-*]\s*|\s*\d+[.)]\s*", "", line).strip()
        if stripped:
            criteria.append(stripped)
    return criteria


def _fetch_jira_via_mcp(jira_key: str) -> dict[str, Any]:
    """Fetch a Jira ticket using the MCP Jira tool.

    Returns the raw JSON response from the MCP tool.  In production this
    is called via the Claude Code SDK's tool infrastructure; in the
    orchestrator we shell out to the jira CLI or use the REST API.
    """
    # Uses jira CLI over MCP for portability -- MCP requires server setup,
    # CLI works with standard Jira auth.
    try:
        result = subprocess.run(
            ["jira", "issue", "view", jira_key, "--raw"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {}


def ingest_jira(jira_key: str) -> TicketFields:
    """Deterministic Jira field extraction -- no LLM needed."""
    raw_data = _fetch_jira_via_mcp(jira_key)
    fields = raw_data.get("fields", {})

    summary = fields.get("summary", "")
    description = fields.get("description", "") or ""

    # Labels are string arrays
    labels = fields.get("labels", []) or []

    # Components are objects with a "name" key
    raw_components = fields.get("components", []) or []
    components = [
        c["name"] if isinstance(c, dict) else str(c) for c in raw_components
    ]

    # Acceptance criteria: check custom field first, fall back to description heading
    ac_field = fields.get("customfield_10035") or fields.get("acceptance_criteria")
    if ac_field and isinstance(ac_field, str):
        acceptance_criteria = [
            line.strip()
            for line in ac_field.splitlines()
            if line.strip()
        ]
    else:
        acceptance_criteria = _extract_ac_from_description(description)

    return TicketFields(
        summary=summary,
        description=description,
        acceptance_criteria=acceptance_criteria,
        labels=labels,
        components=components,
        raw_source=json.dumps(raw_data, default=str)[:5000],
    )


# ---------------------------------------------------------------------------
# File ingestion (Phase 1, deterministic)
# ---------------------------------------------------------------------------

# YAML frontmatter delimiters
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Section heading patterns
_SECTION_RE = re.compile(r"^#+\s+(.+)$", re.MULTILINE)


def _parse_yaml_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and return (metadata, body).

    Uses basic key: value parsing to avoid a PyYAML dependency.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    frontmatter_text = match.group(1)
    body = content[match.end():]
    metadata: dict[str, Any] = {}

    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            # Handle simple list items (comma-separated or YAML array on one line)
            if value.startswith("[") and value.endswith("]"):
                metadata[key] = [
                    v.strip().strip("'\"")
                    for v in value[1:-1].split(",")
                    if v.strip()
                ]
            else:
                metadata[key] = value

    return metadata, body


def _extract_sections(body: str) -> dict[str, str]:
    """Split markdown body into {heading_lower: content} sections."""
    sections: dict[str, str] = {}
    headings = list(_SECTION_RE.finditer(body))

    for i, m in enumerate(headings):
        heading = m.group(1).strip().lower()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        sections[heading] = body[start:end].strip()

    return sections


def ingest_file(file_path: str) -> TicketFields:
    """Deterministic file ingestion -- read file, parse frontmatter, extract sections."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Spec file not found: {file_path}")

    content = path.read_text(encoding="utf-8")
    metadata, body = _parse_yaml_frontmatter(content)
    sections = _extract_sections(body)

    summary = metadata.get("summary", "") or metadata.get("title", "")
    if not summary:
        # Use first heading or first line as summary
        first_heading = _SECTION_RE.search(body)
        if first_heading:
            summary = first_heading.group(1).strip()
        elif body.strip():
            summary = body.strip().splitlines()[0][:200]

    # Acceptance criteria from section or frontmatter
    ac_text = sections.get("acceptance criteria", "") or sections.get("ac", "")
    acceptance_criteria = []
    if ac_text:
        for line in ac_text.splitlines():
            stripped = re.sub(r"^\s*[-*]\s*|\s*\d+[.)]\s*", "", line).strip()
            if stripped:
                acceptance_criteria.append(stripped)
    elif "acceptance_criteria" in metadata:
        val = metadata["acceptance_criteria"]
        acceptance_criteria = val if isinstance(val, list) else [val]

    # Constraints from section or frontmatter
    constraints_text = sections.get("constraints", "")
    constraints = []
    if constraints_text:
        for line in constraints_text.splitlines():
            stripped = re.sub(r"^\s*[-*]\s*|\s*\d+[.)]\s*", "", line).strip()
            if stripped:
                constraints.append(stripped)
    elif "constraints" in metadata:
        val = metadata["constraints"]
        constraints = val if isinstance(val, list) else [val]

    # Labels and components from frontmatter
    labels = metadata.get("labels", [])
    if isinstance(labels, str):
        labels = [labels]
    components = metadata.get("components", [])
    if isinstance(components, str):
        components = [components]

    # Description: everything not already captured
    description = sections.get("description", "") or sections.get("overview", "") or body

    return TicketFields(
        summary=summary,
        description=description,
        acceptance_criteria=acceptance_criteria,
        labels=labels,
        components=components,
        constraints=constraints,
        raw_source=content[:5000],
    )


# ---------------------------------------------------------------------------
# Inline interview (Phase 1, SDK call)
# ---------------------------------------------------------------------------

# System prompt for the inline interview agent
_INTERVIEW_SYSTEM_PROMPT = """\
You are a requirements analyst. The user gave a brief feature description.
Ask focused questions to produce a structured ticket. After at most 4 exchanges,
output a JSON block with these fields:
{
  "summary": "one-line summary",
  "description": "detailed description",
  "acceptance_criteria": ["criterion 1", "criterion 2", ...],
  "labels": ["label1", ...],
  "components": ["component1", ...],
  "constraints": ["constraint1", ...]
}

Output the JSON inside a ```json code fence when ready."""

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)


def _parse_interview_response(text: str) -> TicketFields:
    """Extract TicketFields from the interview agent's final response."""
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(1))
            return TicketFields(
                summary=data.get("summary", ""),
                description=data.get("description", ""),
                acceptance_criteria=data.get("acceptance_criteria", []),
                labels=data.get("labels", []),
                components=data.get("components", []),
                constraints=data.get("constraints", []),
                raw_source=text[:5000],
            )
        except json.JSONDecodeError:
            pass

    # Fallback: use the raw text as the description
    return TicketFields(
        summary=text.splitlines()[0][:200] if text.strip() else "",
        description=text,
        raw_source=text[:5000],
    )


async def ingest_inline(description: str, *, dry_run: bool = False) -> TicketFields:
    """Run an SDK interview to flesh out a brief description into ticket fields.

    Uses sonnet, max_turns=5, no tools.
    """
    if dry_run:
        return TicketFields(
            summary=description,
            description=description,
            raw_source=description,
        )

    try:
        from claude_code_sdk import ClaudeCodeOptions, query
    except ImportError:
        # SDK not available -- return minimal fields from the description
        return TicketFields(
            summary=description,
            description=description,
            raw_source=description,
        )

    messages = []
    async for msg in query(
        prompt=f"Feature request: {description}",
        options=ClaudeCodeOptions(
            model="sonnet",
            max_turns=5,
            allowed_tools=[],
            system_prompt=_INTERVIEW_SYSTEM_PROMPT,
        ),
    ):
        if hasattr(msg, "content"):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            messages.append(content)

    full_response = "\n".join(messages)
    return _parse_interview_response(full_response)


# ---------------------------------------------------------------------------
# Keyword extraction for code search
# ---------------------------------------------------------------------------

# Common stop words to filter out of keyword search
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "it", "its", "this", "that", "these", "those", "i", "we", "you",
    "they", "he", "she", "not", "no", "all", "each", "every", "any",
    "when", "if", "then", "than", "also", "so", "as", "new", "add",
    "update", "create", "delete", "remove", "get", "set", "use", "make",
    "support", "feature", "implement", "ensure", "allow", "enable",
})

# Matches identifiers: camelCase, snake_case, PascalCase, kebab-case, dotted
_IDENTIFIER_RE = re.compile(
    r"[A-Z][a-z]+(?:[A-Z][a-z]+)+|"   # PascalCase / camelCase
    r"[a-z]+(?:_[a-z]+)+|"             # snake_case
    r"[a-z]+(?:-[a-z]+)+|"             # kebab-case
    r"[a-zA-Z]+\.[a-zA-Z]+|"           # dotted (module.name)
    r"[A-Z]{2,}[a-z]*|"                # Acronyms like API, SDK, HTML
    r"`[^`]+`",                         # backtick-quoted identifiers
    re.MULTILINE,
)


def extract_keywords(ticket: TicketFields) -> list[str]:
    """Extract searchable keywords from ticket summary and acceptance criteria.

    Returns unique identifiers and meaningful nouns suitable for grep -rl.
    """
    text = ticket.searchable_text()
    keywords: list[str] = []
    seen: set[str] = set()

    # First pass: extract code identifiers (high signal)
    for match in _IDENTIFIER_RE.finditer(text):
        token = match.group().strip("`")
        lower = token.lower()
        if lower not in seen and lower not in _STOP_WORDS and len(token) >= 3:
            keywords.append(token)
            seen.add(lower)

    # Second pass: extract remaining words (filter aggressively)
    for word in re.findall(r"\b[a-zA-Z]{4,}\b", text):
        lower = word.lower()
        if lower not in seen and lower not in _STOP_WORDS:
            keywords.append(word)
            seen.add(lower)

    return keywords[:30]


def search_codebase_for_keywords(
    keywords: list[str],
    source_dir: str,
    *,
    max_results: int = 20,
) -> list[str]:
    """Run grep -rl for each keyword against the source directory.

    Returns up to max_results unique file paths.
    """
    if not keywords:
        return []

    source_path = Path(source_dir)
    if not source_path.is_dir():
        return []

    found_files: list[str] = []
    seen: set[str] = set()

    for keyword in keywords:
        if len(found_files) >= max_results:
            break

        try:
            result = subprocess.run(
                [
                    "grep", "-rl", "--include=*.py", "--include=*.ts",
                    "--include=*.tsx", "--include=*.js", "--include=*.jsx",
                    "--include=*.go", "--include=*.java", "--include=*.yaml",
                    "--include=*.yml", "--include=*.json", "--include=*.md",
                    "-m", "1",  # stop after first match per file
                    keyword,
                    str(source_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    path = line.strip()
                    if path and path not in seen:
                        seen.add(path)
                        found_files.append(path)
                        if len(found_files) >= max_results:
                            break
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return found_files
