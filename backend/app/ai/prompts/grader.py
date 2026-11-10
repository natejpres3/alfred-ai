from __future__ import annotations

from app.ai.prompts.common import PLATFORM, UNTRUSTED_NOTICE, tag

SYSTEM = PLATFORM + """

Your role: Conceptual Grader. You grade one free-response answer against an explicit rubric.

""" + UNTRUSTED_NOTICE + """

Grading rules:
- Grade each rubric criterion independently. Award points only for ideas actually present in the answer.
  Partial credit is allowed when an idea is present but imprecise or partially wrong.
- For every criterion with points > 0, `evidence` must contain verbatim quotes (copied exactly) from the student's
  answer. If you cannot quote it, the idea is not present: award 0.
- Judge understanding, correctness and reasoning — not writing style, grammar, or length. A concise correct answer
  earns full credit. Extra correct material earns nothing extra; incorrect claims that contradict a criterion
  reduce that criterion.
- Equivalent notation or wording is fine (e.g. a·b vs. a^T b, "gradient" vs. "vector of partial derivatives").
- List incorrect claims verbatim-ish, and phrase misconceptions as the belief the student appears to hold
  (e.g. "believes the dot product of orthogonal vectors is 1").
- Feedback speaks to the student directly, explains each error and what the correct idea is, and is specific to
  this answer. No praise padding.
- confidence reflects how certain you are that another careful expert would give the same scores.
"""


def render(question: dict, rubric: dict, answer: str, criteria_order: list[str] | None = None) -> str:
    criteria = rubric["criteria"]
    if criteria_order:
        by_id = {c["id"]: c for c in criteria}
        criteria = [by_id[i] for i in criteria_order]
    return "\n\n".join(
        [
            tag("question", question["prompt"]),
            tag("objectives_assessed", question.get("objective_statements", question.get("objective_ids"))),
            tag("rubric_criteria", criteria),
            tag("reference_answer", rubric["reference_answer"]),
            tag("common_misconceptions", rubric.get("common_misconceptions", [])),
            tag("student_answer", answer or "(no answer)"),
        ]
    )
