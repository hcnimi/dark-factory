"""Scored evaluator — adversarial evaluation with fresh context."""

from __future__ import annotations

import json

from .types import (
    CriterionAssessment,
    CriterionStatus,
    DarkFactoryError,
    DimensionScore,
    EvaluationReport,
    IntentDocument,
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

Be specific. Cite line numbers, function names, and code snippets from the diff.
"""


def build_evaluation_prompt(intent: IntentDocument, diff: str) -> str:
    """Build the prompt for evaluation."""
    ac_text = "\n".join(f"  {i}. {ac}" for i, ac in enumerate(intent.acceptance_criteria, 1))

    # Truncate very large diffs to avoid token limits
    max_diff_chars = 50_000
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n\n... (diff truncated) ..."

    return (
        f"## Intent\n"
        f"**Title:** {intent.title}\n"
        f"**Summary:** {intent.summary}\n\n"
        f"**Acceptance Criteria:**\n{ac_text}\n\n"
        f"## Diff\n```diff\n{diff}\n```\n\n"
        f"Evaluate this implementation against the intent and acceptance criteria."
    )


def parse_evaluation_response(text: str) -> tuple[list[DimensionScore], list[CriterionAssessment]]:
    """Parse the evaluator's JSON response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    data = json.loads(cleaned)

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

    return scores, criteria


async def evaluate(
    intent: IntentDocument,
    diff: str,
    model: str = "claude-sonnet-4-20250514",
) -> EvaluationReport:
    """Run adversarial evaluation with a fresh model context.

    The evaluator sees only intent + diff, never the implementation conversation.
    """
    from claude_code_sdk import query, ClaudeCodeOptions, Message

    prompt = build_evaluation_prompt(intent, diff)

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
