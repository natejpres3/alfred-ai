"""Deterministic quality control for lessons before publication (docs/02-architecture.md §4.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.lesson import LessonContent, Question

OPEN_ENDED = {"short_answer", "long_answer", "derivation"}
WORKLOAD_TOLERANCE = 1.15


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"errors": self.errors, "warnings": self.warnings, "checks": self.checks}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def latex_problems(text: str) -> list[str]:
    """Cheap KaTeX sanity checks: balanced braces and paired $ delimiters (outside code)."""
    problems = []
    stripped = re.sub(r"```.*?```", "", text, flags=re.S)
    stripped = re.sub(r"`[^`]*`", "", stripped)
    stripped = stripped.replace("\\$", "")
    if stripped.count("$") % 2:
        problems.append("unpaired $ delimiter")
    for seg in re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", stripped, flags=re.S):
        expr = seg[0] or seg[1]
        if _brace_balance(expr) != 0:
            problems.append(f"unbalanced braces in ${expr[:40]}…$")
    if re.search(r"\\(usepackage|documentclass|begin\{document\})", stripped):
        problems.append("LaTeX document commands are not supported")
    return problems


def _brace_balance(expr: str) -> int:
    depth = 0
    for i, ch in enumerate(expr):
        if ch in "{}" and i > 0 and expr[i - 1] == "\\":
            continue
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth < 0:
            return -1
    return depth


def _check_question(q: Question, report: ValidationReport, where: str) -> None:
    g = q.grading
    if q.type in ("mcq", "multi_select"):
        ids = {o.id for o in q.options or []}
        if len(ids) < 2:
            report.errors.append(f"{where}: {q.type} needs at least two options")
        if not g.correct_option_ids or not set(g.correct_option_ids) <= ids:
            report.errors.append(f"{where}: correct_option_ids must reference options")
        if q.type == "mcq" and g.correct_option_ids and len(g.correct_option_ids) != 1:
            report.errors.append(f"{where}: mcq must have exactly one correct option")
        for h in q.hints:
            for o in q.options or []:
                if g.correct_option_ids and o.id in g.correct_option_ids and len(o.text) > 6 and o.text.lower() in h.lower():
                    report.warnings.append(f"{where}: a hint contains the correct option text")
    elif q.type == "numeric":
        if g.numeric is None:
            report.errors.append(f"{where}: numeric question without numeric answer")
        else:
            value = f"{g.numeric.value:g}"
            if any(re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", h) for h in q.hints) and len(value) > 1:
                report.warnings.append(f"{where}: a hint contains the numeric answer")
    elif q.type in OPEN_ENDED:
        if g.rubric is None or not g.rubric.criteria:
            report.errors.append(f"{where}: free-response question needs a rubric")
        else:
            if any(c.points <= 0 for c in g.rubric.criteria):
                report.errors.append(f"{where}: rubric criteria need positive points")
            if len({c.id for c in g.rubric.criteria}) != len(g.rubric.criteria):
                report.errors.append(f"{where}: duplicate rubric criterion ids")
            if not g.rubric.reference_answer.strip():
                report.errors.append(f"{where}: rubric needs a reference answer")
    elif q.type == "code":
        if q.code is None or g.code is None:
            report.errors.append(f"{where}: code question needs code spec and code grading")
        else:
            if not g.code.hidden_tests:
                report.errors.append(f"{where}: code question needs hidden tests")
            names = [t.name for t in q.code.public_tests + g.code.hidden_tests]
            if len(set(names)) != len(names):
                report.errors.append(f"{where}: duplicate test names")
            for t in q.code.public_tests + g.code.hidden_tests:
                if f"def {t.name}(" not in t.code:
                    report.errors.append(f"{where}: test {t.name} does not define a function with that name")
    for text in [q.prompt, *q.hints]:
        for p in latex_problems(text):
            report.errors.append(f"{where}: {p}")


def validate_lesson(
    content: LessonContent,
    spec: dict,
    *,
    budget_minutes: int | None = None,
    allowed_prerequisites: set[str] | None = None,
    previous_prompts: list[str] | None = None,
    execute_code: bool = True,
    check_links: bool = True,
) -> ValidationReport:
    r = ValidationReport()

    # --- structure
    section_ids = [s.id for s in content.sections]
    question_ids = [q.id for q in content.questions]
    all_qids = question_ids + [q.id for q in content.variant_bank]
    if len(set(section_ids)) != len(section_ids):
        r.errors.append("duplicate section ids")
    if len(set(all_qids)) != len(all_qids):
        r.errors.append("duplicate question ids (including variant bank)")
    referenced: set[str] = set()
    resource_ids = {res.id for res in content.resources}
    for s in content.sections:
        if not s.blocks:
            r.errors.append(f"section {s.id} is empty")
        for b in s.blocks:
            if b.type == "question":
                if b.question_id not in question_ids:
                    r.errors.append(f"section {s.id} references unknown question {b.question_id}")
                referenced.add(b.question_id)
            elif b.type == "resource" and b.resource_id not in resource_ids:
                r.errors.append(f"section {s.id} references unknown resource {b.resource_id}")
            elif b.type == "markdown":
                r.errors.extend(f"section {s.id}: {p}" for p in latex_problems(b.text))
            elif b.type == "callout":
                r.errors.extend(f"section {s.id}: {p}" for p in latex_problems(b.text))
            elif b.type == "equation" and _brace_balance(b.latex) != 0:
                r.errors.append(f"section {s.id}: unbalanced braces in equation")
    for qid in question_ids:
        if qid not in referenced:
            r.warnings.append(f"question {qid} is not placed in any section")
    for qid in content.completion.required_question_ids:
        if qid not in question_ids:
            r.errors.append(f"completion references unknown question {qid}")
    for sid in content.completion.required_section_ids:
        if sid not in section_ids:
            r.errors.append(f"completion references unknown section {sid}")
    for q in content.questions:
        if q.required and q.id not in content.completion.required_question_ids:
            r.errors.append(f"required question {q.id} missing from completion.required_question_ids")
    r.checks["structure"] = not r.errors

    # --- objectives ↔ assessment alignment
    obj_ids = {o.id for o in content.objectives}
    spec_objs = {o["key"] for o in spec.get("objectives", [])}
    if content.lesson_key != spec.get("key", content.lesson_key):
        r.errors.append(f"lesson_key {content.lesson_key} does not match spec {spec.get('key')}")
    if spec_objs:
        if missing := spec_objs - obj_ids:
            r.errors.append(f"objectives missing from lesson: {sorted(missing)}")
        if extra := obj_ids - spec_objs:
            r.errors.append(f"lesson defines objectives not in the spec: {sorted(extra)}")
    for q in content.questions + content.variant_bank:
        for o in q.objective_ids:
            if o not in obj_ids:
                r.errors.append(f"question {q.id} tagged with unknown objective {o}")
        if not q.objective_ids:
            r.errors.append(f"question {q.id} is not tagged with an objective")
    for o in content.objectives:
        qs = [q for q in content.questions if o.id in q.objective_ids and q.required]
        if not qs:
            r.errors.append(f"objective {o.id} is not assessed by any required question")
        elif o.critical and len(qs) < 2:
            r.warnings.append(f"critical objective {o.id} is assessed by only one question")
        if o.critical and qs and not any(q.type in OPEN_ENDED | {"code"} for q in qs):
            r.warnings.append(f"critical objective {o.id} has no open-ended or coding question")
    r.checks["alignment"] = not any("objective" in e for e in r.errors)

    # --- question integrity
    for q in content.questions + content.variant_bank:
        _check_question(q, r, f"question {q.id}")

    # --- prerequisites
    if allowed_prerequisites is not None:
        unmet = set(content.prerequisites) - allowed_prerequisites
        if unmet:
            r.errors.append(f"lesson assumes prerequisites the student has not demonstrated: {sorted(unmet)}")
    r.checks["prerequisites"] = allowed_prerequisites is None or not any("prerequisites" in e for e in r.errors)

    # --- workload
    total = sum(s.estimated_minutes for s in content.sections)
    if abs(total - content.estimated_minutes) > max(5, 0.1 * content.estimated_minutes):
        r.warnings.append(f"section minutes sum to {total} but lesson estimate is {content.estimated_minutes}")
    if budget_minutes and total > budget_minutes * WORKLOAD_TOLERANCE:
        r.errors.append(f"lesson needs {total} min, over the {budget_minutes}-min budget (+15% tolerance)")
    r.checks["workload"] = not (budget_minutes and total > budget_minutes * WORKLOAD_TOLERANCE)

    # --- duplication against earlier material
    for q in content.questions:
        for prev in previous_prompts or []:
            if jaccard(q.prompt, prev) >= 0.8:
                r.warnings.append(f"question {q.id} nearly duplicates an earlier question")
                break

    # --- executable checks
    if execute_code:
        _execute_checks(content, r)
    if check_links:
        from app.services.resources import verify_lesson_resources

        verify_lesson_resources(content, r)
    return r


def _execute_checks(content: LessonContent, r: ValidationReport) -> None:
    from app.services.sandbox import SandboxError, get_sandbox

    try:
        sandbox = get_sandbox()
    except SandboxError as e:
        r.warnings.append(f"code not executed: {e}")
        return
    try:
        for s in content.sections:
            for b in s.blocks:
                if b.type == "code" and b.runnable and b.language == "python":
                    res = sandbox.run(b.code, [], [], 20)
                    if res.compile_error:
                        r.errors.append(f"runnable code in section {s.id} fails: {res.compile_error}")
        for q in content.questions + content.variant_bank:
            if q.type == "code" and q.code and q.grading.code:
                tests = [t.model_dump() for t in q.code.public_tests + q.grading.code.hidden_tests]
                res = sandbox.run(q.grading.code.reference_solution, tests, q.code.required_functions, q.code.time_limit_seconds)
                if res.compile_error:
                    r.errors.append(f"question {q.id}: reference solution fails to load: {res.compile_error}")
                failing = [t["name"] for t in res.tests if t["status"] != "passed"]
                if failing:
                    r.errors.append(f"question {q.id}: reference solution fails tests {failing}")
        r.checks["code_executes"] = not any("reference solution" in e or "runnable code" in e for e in r.errors)
    except SandboxError as e:
        r.warnings.append(f"code not executed: {e}")
