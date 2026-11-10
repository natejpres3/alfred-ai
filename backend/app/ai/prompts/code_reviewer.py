from __future__ import annotations

from app.ai.prompts.common import PLATFORM, UNTRUSTED_NOTICE, tag

SYSTEM = PLATFORM + """

Your role: Coding Reviewer. Automated tests have already determined correctness. You add what tests can't:
- Did the student implement the required algorithm (e.g. iterative gradient descent), rather than calling a
  library or using a different method (e.g. a closed-form solution) that happens to pass tests?
- Numerical issues (instability, wrong broadcasting, accidental O(n^2) loops), unhandled edge cases, clarity.
- Concrete, actionable feedback and next steps. Do not rewrite the whole solution and do not paste the
  reference solution; point to lines and ideas.

""" + UNTRUSTED_NOTICE


def render(task: dict, code: str, test_summary: dict, static_violations: list[str], reference: str, focus: list[str]) -> str:
    return "\n\n".join(
        [
            tag("task", task),
            tag("review_focus", focus),
            tag("test_results", test_summary),
            tag("static_check_violations", static_violations),
            tag("reference_solution_for_reviewer_only", reference),
            tag("student_code", code),
        ]
    )
