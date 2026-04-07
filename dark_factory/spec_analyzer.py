"""Spec quality analyzer — post-intent quality check (opt-in)."""

from __future__ import annotations

from .types import (
    DarkFactoryError,
    DimensionScore,
    IntentDocument,
    SpecAnalysisReport,
    extract_json_from_response,
    extract_sdk_result,
)

SPEC_ANALYZER_SYSTEM_PROMPT = """\
You are a spec quality analyzer for a software development pipeline. You receive \
a structured intent document and evaluate its quality on three dimensions.

You MUST respond with valid JSON only, no markdown fencing, no extra text.

JSON schema:
{
  "scores": [
    {
      "dimension": "Clarity",
      "score": <0-10>,
      "justification": "explanation"
    },
    {
      "dimension": "Testability",
      "score": <0-10>,
      "justification": "explanation"
    },
    {
      "dimension": "Completeness",
      "score": <0-10>,
      "justification": "explanation"
    }
  ],
  "suggestions": ["suggestion 1", "suggestion 2", ...]
}

Scoring guide:
- Clarity (0-10): Is the intent unambiguous? Could two engineers build the same thing \
from this spec alone?
- Testability (0-10): Can each acceptance criterion be verified by code inspection or \
automated tests?
- Completeness (0-10): Are edge cases, error handling, and boundaries addressed?

Provide specific, actionable suggestions for improvement. Only include suggestions \
that would materially improve the spec — do not pad with generic advice."""


def build_spec_analysis_prompt(intent: IntentDocument) -> str:
    """Build the prompt for spec analysis."""
    ac_text = "\n".join(f"  {i}. {ac}" for i, ac in enumerate(intent.acceptance_criteria, 1))
    return (
        f"## Intent Document\n"
        f"**Title:** {intent.title}\n"
        f"**Summary:** {intent.summary}\n\n"
        f"**Acceptance Criteria:**\n{ac_text}\n\n"
        f"Evaluate the quality of this intent document."
    )


def parse_spec_analysis_response(text: str) -> tuple[list[DimensionScore], list[str]]:
    """Parse the analyzer's JSON response."""
    data = extract_json_from_response(text)

    scores = [
        DimensionScore(
            dimension=s["dimension"],
            score=int(s["score"]),
            justification=s["justification"],
        )
        for s in data["scores"]
    ]

    suggestions = data.get("suggestions", [])

    return scores, suggestions


async def analyze_spec(
    intent: IntentDocument,
    model: str = "claude-sonnet-4-20250514",
) -> SpecAnalysisReport:
    """Run spec quality analysis via SDK call."""
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    prompt = build_spec_analysis_prompt(intent)

    messages: list[Message] = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=SPEC_ANALYZER_SYSTEM_PROMPT,
            model=model,
            max_turns=3,
            allowed_tools=[],
        ),
    ):
        messages.append(msg)

    full_text, cost = extract_sdk_result(messages)
    if not full_text.strip():
        raise DarkFactoryError("Spec analyzer returned empty response")

    scores, suggestions = parse_spec_analysis_response(full_text)

    return SpecAnalysisReport(
        scores=scores,
        suggestions=suggestions,
        model_used=model,
        cost_usd=cost,
    )
