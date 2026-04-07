"""Adaptive input assessment and amplification."""

from __future__ import annotations

import json

from .types import InterviewQA, SourceInfo, SourceKind, extract_sdk_result

INTERVIEW_SYSTEM_PROMPT = """\
You analyze feature requests for a software development pipeline.
Examine the input for ambiguities, unstated assumptions, missing edge cases,
and unclear requirements.

If the input is clear and complete enough to implement, respond: {"questions": []}
If clarification would materially improve the implementation, respond with up to 5
targeted questions: {"questions": ["Q1", "Q2", ...]}

Only ask questions that would change what gets built. Do not ask about implementation
approach — the implementing agent decides that. Focus on product-level ambiguities:
what should happen, not how to build it."""


def build_interview_prompt(source: SourceInfo) -> str:
    """Build prompt with raw input for assessment.

    For FILE sources, reads file content. For INLINE, uses raw text.
    """
    if source.kind == SourceKind.FILE:
        from pathlib import Path
        content = Path(source.raw).read_text()
        return (
            f"Assess this feature specification for ambiguities or missing details:\n\n"
            f"{content}"
        )
    if source.kind == SourceKind.JIRA:
        return (
            f"Assess this Jira ticket for ambiguities or missing details:\n\n"
            f"Ticket: {source.raw}\n"
            f"(Ticket details would be fetched from Jira API)"
        )
    # INLINE
    return (
        f"Assess this feature request for ambiguities or missing details:\n\n"
        f"{source.raw}"
    )


def parse_interview_response(text: str) -> list[str]:
    """Parse {"questions": [...]} JSON. Strip code fences. Returns list (may be empty)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    data = json.loads(cleaned)
    return data.get("questions", [])


async def assess_and_probe(source: SourceInfo) -> tuple[list[str], float]:
    """SDK call to Sonnet to assess input for ambiguities.

    Returns (questions, cost). Empty list means input is clear.
    """
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    prompt = build_interview_prompt(source)

    messages: list[Message] = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            model="claude-sonnet-4-20250514",
            max_turns=3,
            allowed_tools=[],
        ),
    ):
        messages.append(msg)

    full_text, cost = extract_sdk_result(messages)
    if not full_text.strip():
        return [], cost

    questions = parse_interview_response(full_text)
    return questions, cost


def collect_answers_tty(questions: list[str]) -> list[InterviewQA]:
    """Present questions via input(), collect answers. Numbered prompts."""
    qas = []
    for i, question in enumerate(questions, 1):
        print(f"\n  Q{i}: {question}")
        answer = input(f"  A{i}: ").strip()
        qas.append(InterviewQA(question=question, answer=answer))
    return qas


def format_amplification_context(qas: list[InterviewQA]) -> str:
    """Format Q&A as text for inclusion in intent prompt.

    Truncates to 5000 chars to avoid bloating.
    """
    lines = []
    for i, qa in enumerate(qas, 1):
        lines.append(f"Q{i}: {qa.question}")
        lines.append(f"A{i}: {qa.answer}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 5000:
        text = text[:5000] + "\n... (truncated)"
    return text
