from __future__ import annotations

from app.ai.prompts.common import PLATFORM, UNTRUSTED_NOTICE, tag

DIAGNOSIS_SYSTEM = PLATFORM + """

Your role: Remediation Planner (diagnosis step). From graded answers, identify for each failed objective the most
likely underlying misconception, citing evidence from the student's answers, and whether the root cause is a
missing prerequisite concept (give its concept key from the provided list, else null).

""" + UNTRUSTED_NOTICE

CONTENT_SYSTEM = PLATFORM + """

Your role: Remediation Planner (content step). The student failed specific objectives. Write a focused
mini-lesson (at most 25 minutes) that:
- addresses the diagnosed misconceptions directly (name the wrong belief, show why it fails, give the right one);
- uses a DIFFERENT explanation strategy from those already used (listed below) — e.g. worked examples, contrast
  cases, geometric picture, re-derivation from first principles, analogy, numeric experiment;
- if prerequisite concepts are listed, briefly re-teaches them first;
- ends with new practice questions on every failed objective: at least two per objective, including at least one
  open-ended question requiring explanation. Questions must be genuinely different from the previous questions
  shown (different numbers alone is not enough for conceptual items). Every free-response question has a rubric.
Follow the same JSON conventions as regular lessons (LaTeX, rubrics, hints that never reveal answers).
"""


def render_diagnosis(ctx: dict) -> str:
    return "\n\n".join(
        [
            tag("failed_objectives", ctx["failed_objectives_detail"]),
            tag("graded_answers", ctx["graded_answers"]),
            tag("prerequisite_concepts", ctx["prerequisite_concepts"]),
        ]
    )


def render_content(ctx: dict) -> str:
    return "\n\n".join(
        [
            tag("failed_objectives", ctx["failed_objectives_detail"]),
            tag("diagnosis", ctx["diagnosis"]),
            tag("prerequisites_to_reteach", ctx["prerequisites_to_reteach"]),
            tag("used_strategies", ctx["used_strategies"]),
            tag("previous_questions", ctx["previous_questions"]),
            tag("lesson_summary", ctx["lesson_summary"]),
            f"Question ids must start with 'r{ctx['attempt']}-'. Section ids must start with 'rs{ctx['attempt']}-'.",
        ]
    )
