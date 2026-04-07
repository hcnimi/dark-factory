"""Intent clarification — produces a structured IntentDocument from raw input."""

from __future__ import annotations

import json

from .types import DarkFactoryError, IntentDocument, SourceInfo, SourceKind, extract_sdk_result

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


def build_intent_prompt(source: SourceInfo, interview_context: str | None = None) -> str:
    """Build the user prompt for intent clarification."""
    if source.kind == SourceKind.INLINE:
        prompt = (
            f"Produce an intent document for this feature request:\n\n"
            f"{source.raw}"
        )
    elif source.kind == SourceKind.FILE:
        # For file input, the raw field contains the path; read it
        from pathlib import Path
        content = Path(source.raw).read_text()
        prompt = (
            f"Produce an intent document based on this spec file:\n\n"
            f"{content}"
        )
    else:
        # Jira — not in MVP, but stub the prompt
        prompt = (
            f"Produce an intent document for Jira ticket {source.raw}.\n"
            f"(Ticket details would be fetched from Jira API)"
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
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    data = json.loads(cleaned)
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

    Returns (IntentDocument, cost_usd).
    """
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
