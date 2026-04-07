"""Intent clarification — produces a structured IntentDocument from raw input.

For structured spec inputs (FILE/DIRECTORY with requirement/scenario markers),
uses extraction mode that preserves all detail. For inline/vague inputs,
uses condensation mode that synthesizes structure from scratch.
"""

from __future__ import annotations

import json
import sys

from .types import DarkFactoryError, IntentDocument, SourceInfo, SourceKind, extract_json_from_response, extract_sdk_result, read_source_content

# Markers that indicate a structured spec (vs. prose or vague description)
_STRUCTURED_MARKERS = [
    "### Requirement",
    "#### Scenario",
    "## ADDED Requirements",
    "## CHANGED Requirements",
    "- **GIVEN**",
    "- **WHEN**",
    "- **THEN**",
]


def is_structured_spec(content: str) -> bool:
    """Detect whether content is a structured spec (vs. prose/vague description).

    Returns True if the content contains at least 2 structured markers
    (requirement headers, scenario blocks, or Gherkin keywords).
    """
    count = sum(1 for marker in _STRUCTURED_MARKERS if marker in content)
    return count >= 2


INTENT_SYSTEM_PROMPT = """\
You are an intent clarifier for a software development pipeline. Your job is to \
take a feature description and produce a structured intent document.

You MUST respond with valid JSON only, no markdown fencing, no extra text.

JSON schema:
{
  "title": "short feature title",
  "summary": "1-3 sentence description of what to build and why",
  "acceptance_criteria": ["criterion 1", "criterion 2", ...]
}

Rules:
- Title should be concise (under 80 chars)
- Summary explains the what and why
- Each acceptance criterion must be concrete and testable
- Aim for 3-7 acceptance criteria
- Criteria should be verifiable by inspecting code or running tests
"""

EXTRACT_INTENT_SYSTEM_PROMPT = """\
You are a spec structurer for a software development pipeline. Your job is to \
extract (NOT condense) a structured intent document from a detailed specification.

You MUST respond with valid JSON only, no markdown fencing, no extra text.

JSON schema:
{
  "title": "short feature title",
  "summary": "1-3 sentence description of what the spec covers and why",
  "acceptance_criteria": ["criterion 1", "criterion 2", ...]
}

Rules:
- Title should be concise (under 80 chars)
- Summary explains the overall scope
- CRITICAL: Extract EVERY requirement and scenario as a separate acceptance criterion
- Each scenario (GIVEN/WHEN/THEN) becomes one criterion — preserve the full scenario text
- Each requirement without scenarios becomes one criterion
- Do NOT summarize or condense — your job is to STRUCTURE, not reduce
- Preserve threshold values, error codes, data model fields, and specific details verbatim
- It is perfectly fine to have 20, 30, or 50+ acceptance criteria
- Order criteria by the spec section they appear in
"""


def build_extraction_prompt(content: str, interview_context: str | None = None) -> str:
    """Build the prompt for structured spec extraction."""
    prompt = (
        "Extract an intent document from this structured specification. "
        "Preserve ALL requirements and scenarios as individual acceptance criteria.\n\n"
        f"{content}"
    )

    if interview_context:
        prompt += (
            "\n\n## Amendments from Clarification\n\n"
            f"{interview_context}\n\n"
            "These clarifications take priority over the original spec where they conflict. "
            "Incorporate them as additional or modified acceptance criteria."
        )

    return prompt


async def extract_intent_from_spec(
    source: SourceInfo,
    interview_context: str | None = None,
    content: str | None = None,
) -> tuple[IntentDocument, float]:
    """Extract intent from a structured spec, preserving all detail.

    Uses a lighter LLM call that structures rather than condenses.
    On failure, falls back to the standard condensation path.
    Returns (IntentDocument, cost_usd).
    """
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    if content is None:
        content = read_source_content(source)
    prompt = build_extraction_prompt(content, interview_context)

    try:
        messages: list[Message] = []
        async for msg in query(
            prompt=prompt,
            options=ClaudeCodeOptions(
                system_prompt=EXTRACT_INTENT_SYSTEM_PROMPT,
                model="claude-sonnet-4-20250514",
                max_turns=3,
                allowed_tools=[],
            ),
        ):
            messages.append(msg)

        full_text, cost = extract_sdk_result(messages)
        if not full_text.strip():
            raise DarkFactoryError("Intent extraction returned empty response")

        return parse_intent_response(full_text), cost

    except (DarkFactoryError, json.JSONDecodeError, KeyError, ValueError) as e:
        # Extraction is best-effort with fallback to condensation.
        # Covers DarkFactoryError (SDK/parse), JSONDecodeError, missing fields (KeyError),
        # and invalid values (ValueError). Unexpected errors propagate.
        print(f"  Extraction failed ({e}), falling back to condensation", file=sys.stderr)
        return await _clarify_intent_condensation(source, interview_context)


def build_intent_prompt(source: SourceInfo, interview_context: str | None = None) -> str:
    """Build the user prompt for intent clarification."""
    content = read_source_content(source)

    if source.kind == SourceKind.INLINE:
        prompt = (
            f"Produce an intent document for this feature request:\n\n"
            f"{content}"
        )
    elif source.kind in (SourceKind.FILE, SourceKind.DIRECTORY):
        label = "spec file" if source.kind == SourceKind.FILE else "spec files"
        prompt = (
            f"Produce an intent document based on {'this' if source.kind == SourceKind.FILE else 'these'} {label}:\n\n"
            f"{content}"
        )
    else:
        raise DarkFactoryError(
            "JIRA integration is not yet implemented. "
            "Provide a file path or inline description instead."
        )

    if interview_context:
        prompt += (
            "\n\n## Additional Context from Clarification\n\n"
            f"{interview_context}\n\n"
            "Use this context to produce more precise and complete acceptance criteria "
            "that address the edge cases and assumptions surfaced above."
        )

    return prompt


def parse_intent_response(text: str) -> IntentDocument:
    """Parse the model's JSON response into an IntentDocument."""
    data = extract_json_from_response(text)
    return IntentDocument(
        title=data["title"],
        summary=data["summary"],
        acceptance_criteria=data["acceptance_criteria"],
    )


async def clarify_intent(
    source: SourceInfo,
    interview_context: str | None = None,
) -> tuple[IntentDocument, float]:
    """Run intent clarification via SDK call to Sonnet.

    For structured specs (FILE/DIRECTORY with requirement/scenario markers),
    uses extraction mode that preserves all detail. For inline/vague inputs,
    uses condensation mode that synthesizes structure.

    Returns (IntentDocument, cost_usd).
    """
    # Route structured specs to extraction mode
    if source.kind in (SourceKind.FILE, SourceKind.DIRECTORY):
        content = read_source_content(source)
        if is_structured_spec(content):
            print("  Using extraction mode (structured spec detected)", file=sys.stderr)
            return await extract_intent_from_spec(source, interview_context, content=content)

    return await _clarify_intent_condensation(source, interview_context)


async def _clarify_intent_condensation(
    source: SourceInfo,
    interview_context: str | None = None,
) -> tuple[IntentDocument, float]:
    """Standard condensation path — synthesizes structure from vague input."""
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    prompt = build_intent_prompt(source, interview_context)

    messages: list[Message] = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=INTENT_SYSTEM_PROMPT,
            model="claude-sonnet-4-20250514",
            max_turns=3,
            allowed_tools=[],
        ),
    ):
        messages.append(msg)

    full_text, cost = extract_sdk_result(messages)
    if not full_text.strip():
        raise DarkFactoryError("Intent clarification returned empty response")

    return parse_intent_response(full_text), cost
