"""Scored evaluator — adversarial evaluation with fresh context."""

from __future__ import annotations

from .types import (
    CriterionAssessment,
    CriterionStatus,
    DarkFactoryError,
    DimensionScore,
    EvaluationReport,
    IntentDocument,
    extract_json_from_response,
    extract_sdk_result,
)

EVALUATOR_SYSTEM_PROMPT = """\
You are a code evaluator for a software development pipeline. You receive an \
intent document (what was requested) and a git diff (what was implemented).

You MUST evaluate the implementation on three dimensions and check each \
acceptance criterion. Respond with valid JSON only, no markdown fencing.

JSON schema:
{
  "scores": [
    {
      "dimension": "Intent Fidelity",
      "score": <0-10>,
      "justification": "explanation citing evidence from the diff"
    },
    {
      "dimension": "Correctness",
      "score": <0-10>,
      "justification": "explanation citing evidence from the diff"
    },
    {
      "dimension": "Integration",
      "score": <0-10>,
      "justification": "explanation citing evidence from the diff"
    }
  ],
  "criteria": [
    {
      "criterion": "the acceptance criterion text",
      "status": "met" | "partial" | "not_met",
      "evidence": "evidence from the diff"
    }
  ]
}

Scoring guide:
- Intent Fidelity (0-10): Does the implementation match what was requested? \
Are all acceptance criteria addressed?
- Correctness (0-10): Is the code correct? Edge cases handled? Any bugs, \
security issues, or logic errors?
- Integration (0-10): Does the code integrate with the existing codebase? \
Follows conventions, patterns, and style?

For each acceptance criterion, mark as:
- "met": fully implemented with evidence
- "partial": partially implemented
- "not_met": not implemented or missing

If an "Original Specification" section is provided, use it as the primary reference \
for understanding requirements. The acceptance criteria are derived from this \
specification — evaluate against the full detail of the original spec, not just the \
summarized criteria.

Be specific. Cite line numbers, function names, and code snippets from the diff.
"""


# Context budget scales with model capability
_MODEL_LIMITS: dict[str, tuple[int, int]] = {
    # (max_diff_chars, max_context_chars)
    "claude-opus-4-6": (500_000, 200_000),  # 1M context window
}
_DEFAULT_LIMITS = (50_000, 30_000)  # Conservative for unknown models


def build_evaluation_prompt(
    intent: IntentDocument, diff: str, source_context: str = "", model: str = "",
) -> str:
    """Build the prompt for evaluation.

    When source_context is provided, it is included as the original specification
    so the evaluator can assess against the full detail, not just the summarized
    acceptance criteria. Truncation limits scale with the model's context window.
    """
    ac_text = "\n".join(f"  {i}. {ac}" for i, ac in enumerate(intent.acceptance_criteria, 1))

    # Dynamic token budget: diff gets priority, source_context fills remainder
    max_diff_chars, max_context_chars = _MODEL_LIMITS.get(model, _DEFAULT_LIMITS)
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n\n... (diff truncated) ..."
    if source_context and len(source_context) > max_context_chars:
        source_context = source_context[:max_context_chars] + "\n\n... (source context truncated) ..."

    parts = [
        f"## Intent\n"
        f"**Title:** {intent.title}\n"
        f"**Summary:** {intent.summary}\n\n"
        f"**Acceptance Criteria:**\n{ac_text}\n\n",
    ]

    if source_context:
        parts.append(f"## Original Specification\n\n{source_context}\n\n")

    parts.append(
        f"## Diff\n```diff\n{diff}\n```\n\n"
        f"Evaluate this implementation against the intent and acceptance criteria."
    )
    return "".join(parts)


def parse_evaluation_response(text: str) -> tuple[list[DimensionScore], list[CriterionAssessment]]:
    """Parse the evaluator's JSON response."""
    data = extract_json_from_response(text)

    try:
        scores = [
            DimensionScore(
                dimension=s["dimension"],
                score=int(s["score"]),
                justification=s["justification"],
            )
            for s in data["scores"]
        ]

        criteria = [
            CriterionAssessment(
                criterion=c["criterion"],
                status=CriterionStatus(c["status"]),
                evidence=c["evidence"],
            )
            for c in data.get("criteria", [])
        ]
    except (KeyError, ValueError, TypeError) as e:
        raise DarkFactoryError(f"Invalid evaluation response structure: {e}") from e

    return scores, criteria


async def evaluate(
    intent: IntentDocument,
    diff: str,
    model: str = "claude-opus-4-6",
    source_context: str = "",
) -> EvaluationReport:
    """Run adversarial evaluation with a fresh model context.

    The evaluator sees intent + diff + optional original specification,
    never the implementation conversation.
    """
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    prompt = build_evaluation_prompt(intent, diff, source_context, model=model)

    messages: list[Message] = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=EVALUATOR_SYSTEM_PROMPT,
            model=model,
            max_turns=3,
            allowed_tools=[],
        ),
    ):
        messages.append(msg)

    full_text, cost = extract_sdk_result(messages)
    if not full_text.strip():
        raise DarkFactoryError("Evaluator returned empty response")

    scores, criteria = parse_evaluation_response(full_text)

    return EvaluationReport(
        scores=scores,
        criteria=criteria,
        model_used=model,
        cost_usd=cost,
    )
