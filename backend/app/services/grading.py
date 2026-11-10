"""Assessment Service: grade submissions.

Deterministic graders for objective items, rubric-based LLM grading (with evidence verification,
second pass, and flagging) for free response, and sandboxed tests + static checks + AI review for
code. The pass decision is non-compensatory (docs/04 §3).
"""

from __future__ import annotations

import ast
import hashlib
import math
import operator
import random
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import code_reviewer as code_prompt
from app.ai.prompts import grader as grader_prompt
from app.ai.provider import AIError, get_provider
from app.config import ProgressionThresholds, get_settings
from app.db import utcnow
from app.models import Assessment, Grade, LearningObjective, RubricResult, Submission
from app.schemas.grading import CodeReview, RubricGrade
from app.schemas.lesson import Question
from app.services.sandbox import get_sandbox, static_check

GRADER_VERSION = "2026.11.1"
SECOND_PASS_CONFIDENCE = 0.7
BORDERLINE_BAND = 0.10
DISAGREEMENT_FRACTION = 0.5
ALGORITHM_CAP = 0.5


@dataclass
class QuestionResult:
    question_key: str
    grader: str
    score: float
    max_score: float
    category: str
    objective_ids: list[str]
    critical: bool
    required: bool
    answered: bool
    criteria: list[dict] = field(default_factory=list)
    confidence: float = 1.0
    correct_concepts: list[str] = field(default_factory=list)
    missing_concepts: list[str] = field(default_factory=list)
    incorrect_claims: list[str] = field(default_factory=list)
    misconceptions: list[str] = field(default_factory=list)
    feedback: str = ""
    next_steps: list[str] = field(default_factory=list)
    meets_mastery: bool = False
    review_status: str = "auto"
    details: dict = field(default_factory=dict)
    ai_call_ids: list[str] = field(default_factory=list)
    rubric_id: str | None = None

    @property
    def fraction(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0


# ------------------------------------------------------------------ deterministic

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_NAMES = {"pi": math.pi, "e": math.e}
_FUNCS = {"sqrt": math.sqrt, "ln": math.log, "log": math.log, "exp": math.exp, "sin": math.sin, "cos": math.cos}


def parse_numeric(text: str) -> float | None:
    """Parse '3/4', '2*pi', '1e-3', 'sqrt(2)/2', '−6' safely (AST whitelist, no eval)."""
    if text is None:
        return None
    s = str(text).strip().replace("−", "-").replace("^", "**").replace("π", "pi").replace(",", "")
    if not s or len(s) > 100:
        return None
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError:
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            right = ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](ev(node.left), right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _NAMES:
            return _NAMES[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
            return _FUNCS[node.func.id](ev(node.args[0]))
        raise ValueError("disallowed expression")

    try:
        v = ev(tree)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return v if math.isfinite(v) else None


def _base(q: Question, grader: str, answered: bool) -> QuestionResult:
    return QuestionResult(
        question_key=q.id, grader=grader, score=0.0, max_score=q.points, category=q.category,
        objective_ids=q.objective_ids, critical=q.critical, required=q.required, answered=answered,
    )


def grade_choice(q: Question, answer: dict | None) -> QuestionResult:
    selected = set((answer or {}).get("selected", []))
    r = _base(q, "deterministic", bool(selected))
    correct = set(q.grading.correct_option_ids or [])
    if q.type == "mcq":
        frac = 1.0 if selected == correct else 0.0
    else:
        frac = max(0.0, (len(selected & correct) - len(selected - correct)) / max(1, len(correct)))
    r.score = q.points * frac
    r.meets_mastery = frac == 1.0
    r.feedback = "Correct." if frac == 1.0 else ("Partially correct." if frac > 0 else "Incorrect.")
    r.feedback += " " + q.grading.explanation
    r.details = {"selected": sorted(selected), "correct": sorted(correct)}
    return r


def grade_numeric(q: Question, answer: dict | None) -> QuestionResult:
    raw = (answer or {}).get("value")
    r = _base(q, "deterministic", raw not in (None, ""))
    spec = q.grading.numeric
    value = parse_numeric(raw) if raw is not None else None
    if value is None:
        r.feedback = ("Could not read your answer as a number. " if r.answered else "No answer. ") + q.grading.explanation
        r.details = {"submitted": raw}
        return r
    tol = max(spec.abs_tol, spec.rel_tol * abs(spec.value))
    ok = abs(value - spec.value) <= tol
    r.score = q.points if ok else 0.0
    r.meets_mastery = ok
    r.feedback = ("Correct. " if ok else f"Incorrect (you entered {value:g}). ") + q.grading.explanation
    r.details = {"submitted": raw, "parsed": value}
    return r


# ------------------------------------------------------------------ rubric (LLM)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


def evidence_found(quote: str, answer: str) -> bool:
    nq, na = _norm(quote), _norm(answer)
    if not nq:
        return False
    if nq in na:
        return True
    # tolerate light paraphrase/truncation inside the quote: ≥ 85% of its words, in the answer
    words = nq.split()
    return len(words) >= 4 and sum(w in na.split() for w in words) / len(words) >= 0.85


def _sanitize(grade: RubricGrade, rubric: dict, answer: str) -> tuple[dict[str, dict], bool]:
    """Clamp scores to criterion maxima, recompute nothing from the model's arithmetic, and zero any
    awarded criterion whose evidence does not occur in the answer. Returns (by_criterion, evidence_failed)."""
    by_id = {c["id"]: c for c in rubric["criteria"]}
    out: dict[str, dict] = {}
    failed = False
    for cs in grade.criteria:
        c = by_id.get(cs.criterion_id)
        if c is None:
            continue
        pts = min(max(cs.points_awarded, 0.0), c["points"])
        verified = [e for e in cs.evidence if evidence_found(e, answer)]
        if pts > 0 and not verified:
            pts, failed = 0.0, True
        out[c["id"]] = {"criterion_id": c["id"], "points_awarded": pts, "max_points": c["points"],
                        "evidence": verified, "rationale": cs.rationale,
                        "required_for_mastery": c.get("required_for_mastery", False), "description": c["description"]}
    for cid, c in by_id.items():  # criteria the model skipped get zero
        out.setdefault(cid, {"criterion_id": cid, "points_awarded": 0.0, "max_points": c["points"], "evidence": [],
                             "rationale": "Not addressed by the grader.", "required_for_mastery": c.get("required_for_mastery", False),
                             "description": c["description"]})
    return out, failed


def grade_rubric(q: Question, answer: dict | None, *, user_id: str | None, thresholds: ProgressionThresholds,
                 objective_statements: dict[str, str]) -> QuestionResult:
    text = ((answer or {}).get("text") or "").strip()
    r = _base(q, "rubric_llm", bool(text))
    rubric = q.grading.rubric.model_dump()
    total = sum(c["points"] for c in rubric["criteria"])
    if not text:
        r.feedback = "No answer submitted."
        r.criteria = [{"criterion_id": c["id"], "points_awarded": 0, "max_points": c["points"], "evidence": [],
                       "rationale": "No answer.", "description": c["description"]} for c in rubric["criteria"]]
        return r
    provider = get_provider()
    qctx = {"prompt": q.prompt, "objective_statements": [objective_statements.get(o, o) for o in q.objective_ids]}
    threshold = thresholds.category(q.category)

    def one_pass(n: int, order: list[str] | None):
        res = provider.structured(
            role="grader", system=grader_prompt.SYSTEM, prompt=grader_prompt.render(qctx, rubric, text, order),
            schema=RubricGrade, user_id=user_id,
            context={"question_id": q.id, "pass": n, "answer": text, "rubric": rubric},
        )
        crit, failed = _sanitize(res.value, rubric, text)
        return res, crit, failed

    res1, crit1, failed1 = one_pass(1, None)
    r.ai_call_ids.append(res1.call_id)
    frac1 = sum(c["points_awarded"] for c in crit1.values()) / total
    final, review, conf, primary = crit1, "auto", res1.value.confidence, res1.value
    if res1.value.confidence < SECOND_PASS_CONFIDENCE or abs(frac1 - threshold) <= BORDERLINE_BAND or failed1:
        order = [c["id"] for c in rubric["criteria"]]
        random.Random(int(hashlib.sha256(q.id.encode()).hexdigest(), 16)).shuffle(order)
        res2, crit2, failed2 = one_pass(2, order)
        r.ai_call_ids.append(res2.call_id)
        disagree = any(
            abs(crit1[cid]["points_awarded"] - crit2[cid]["points_awarded"]) > DISAGREEMENT_FRACTION * crit1[cid]["max_points"]
            for cid in crit1
        )
        final = {}
        for cid in crit1:
            merged = dict(crit1[cid])
            merged["points_awarded"] = (crit1[cid]["points_awarded"] + crit2[cid]["points_awarded"]) / 2
            merged["evidence"] = sorted(set(crit1[cid]["evidence"]) | set(crit2[cid]["evidence"]))
            merged["second_pass_points"] = crit2[cid]["points_awarded"]
            final[cid] = merged
        review = "flagged" if disagree else "second_pass"
        conf = min(res1.value.confidence, res2.value.confidence)
        if res2.value.confidence > res1.value.confidence:
            primary = res2.value
        r.details["evidence_verification_failed"] = failed1 or failed2

    r.criteria = [final[c["id"]] for c in rubric["criteria"]]
    r.score = q.points * sum(c["points_awarded"] for c in r.criteria) / total
    r.confidence, r.review_status = conf, review
    r.correct_concepts, r.missing_concepts = primary.correct_concepts, primary.missing_concepts
    r.incorrect_claims, r.misconceptions = primary.incorrect_claims, primary.misconceptions
    r.feedback, r.next_steps = primary.feedback, primary.next_steps
    required_ok = all(c["points_awarded"] >= 0.5 * c["max_points"] for c in r.criteria if c.get("required_for_mastery"))
    r.meets_mastery = r.fraction >= threshold and required_ok
    r.details["reference_explanation"] = q.grading.explanation
    if get_provider().name == "fake":
        r.details["offline_grader"] = True
    return r


# ------------------------------------------------------------------ code


def run_code_question(code: str, spec: dict, grading: dict) -> tuple[dict, list[str]]:
    """Shared by lesson code questions and project milestones. Returns (report, violations)."""
    violations = static_check(
        code, forbidden_imports=grading.get("forbidden_imports", []), allowed_imports=spec.get("allowed_imports"),
        forbidden_calls=grading.get("forbidden_calls", []), required_functions=spec.get("required_functions", []),
    )
    if any(v.startswith("SyntaxError") for v in violations):
        return {"compile_error": violations[0], "public": [], "hidden": {"passed": 0, "total": len(grading["hidden_tests"])},
                "pass_rate": 0.0, "stdout": ""}, violations
    sandbox = get_sandbox()
    limit = spec.get("time_limit_seconds", 10)
    public = sandbox.run(code, spec.get("public_tests", []), spec.get("required_functions", []), limit)
    hidden = sandbox.run(code, grading["hidden_tests"], spec.get("required_functions", []), limit)
    pw = {t["name"]: t.get("weight", 1.0) for t in spec.get("public_tests", [])}
    hw = {t["name"]: t.get("weight", 1.0) for t in grading["hidden_tests"]}
    total = earned = 0.0
    for t in public.tests:
        total += pw.get(t["name"], 1.0)
        earned += pw.get(t["name"], 1.0) if t["status"] == "passed" else 0
    for t in hidden.tests:
        total += 2 * hw.get(t["name"], 1.0)
        earned += 2 * hw.get(t["name"], 1.0) if t["status"] == "passed" else 0
    report = {
        "compile_error": public.compile_error,
        "missing_functions": public.missing_functions,
        "public": public.tests,  # names + messages are fine to show
        "hidden": {"passed": sum(t["status"] == "passed" for t in hidden.tests), "total": len(grading["hidden_tests"]),
                   "timeouts": sum(t["status"] == "timeout" for t in hidden.tests)},
        "pass_rate": 0.0 if public.compile_error else (earned / total if total else 0.0),
        "stdout": public.stdout[-2000:],
    }
    return report, violations


def review_code(task: dict, code: str, report: dict, violations: list[str], grading: dict, user_id: str | None) -> tuple[dict | None, str | None]:
    try:
        res = get_provider().structured(
            role="code_reviewer", system=code_prompt.SYSTEM,
            prompt=code_prompt.render(task, code, {k: report[k] for k in ("public", "hidden", "pass_rate", "compile_error")},
                                      violations, grading.get("reference_solution", ""), grading.get("review_focus", [])),
            schema=CodeReview, user_id=user_id, context={"static_violations": violations},
        )
        return res.value.model_dump(), res.call_id
    except AIError as e:
        return {"unavailable": str(e)}, None


def score_code(report: dict, violations: list[str], review: dict | None) -> tuple[float, list[str]]:
    """Fraction in [0,1] after caps, and human-readable reasons for caps."""
    frac = report["pass_rate"]
    reasons = []
    hard = [v for v in violations if "not allowed" in v or "not in the allowed list" in v]
    if hard:
        frac = min(frac, ALGORITHM_CAP)
        reasons.append("Uses a disallowed import/call for a from-scratch task (score capped at 50%).")
    if review and review.get("implements_required_algorithm") is False and (hard or review.get("confidence", 0) >= 0.8):
        if frac > ALGORITHM_CAP:
            frac = ALGORITHM_CAP
            reasons.append("The reviewer found the required algorithm was not implemented (score capped at 50%).")
    return frac, reasons


def grade_code_question(q: Question, answer: dict | None, *, user_id: str | None, thresholds: ProgressionThresholds) -> QuestionResult:
    code = (answer or {}).get("code") or ""
    r = _base(q, "code", bool(code.strip()) and code.strip() != (q.code.starter_code.strip() if q.code else ""))
    if not r.answered:
        r.feedback = "No code submitted (or unchanged starter code)."
        return r
    spec, grading = q.code.model_dump(), q.grading.code.model_dump()
    report, violations = run_code_question(code, spec, grading)
    review, call_id = review_code({"prompt": q.prompt, "required_functions": spec["required_functions"]}, code, report, violations, grading, user_id)
    if call_id:
        r.ai_call_ids.append(call_id)
    frac, cap_reasons = score_code(report, violations, review)
    r.score = q.points * frac
    r.meets_mastery = frac >= thresholds.coding
    parts = []
    if report["compile_error"]:
        parts.append(f"Your code failed to load: {report['compile_error']}")
    parts.append(f"Public tests: {sum(t['status'] == 'passed' for t in report['public'])}/{len(report['public'])} passed. "
                 f"Hidden tests: {report['hidden']['passed']}/{report['hidden']['total']} passed.")
    parts += cap_reasons
    parts += [f"Static check: {v}" for v in violations]
    if review and review.get("feedback"):
        parts.append(review["feedback"])
    r.feedback = "\n\n".join(parts)
    r.next_steps = (review or {}).get("next_steps", [])
    r.confidence = (review or {}).get("confidence", 1.0) if review and "unavailable" not in review else 1.0
    r.details = {"tests": report, "static_violations": violations, "review": review, "reference_explanation": q.grading.explanation}
    return r


# ------------------------------------------------------------------ submission


def grade_question(q: Question, answer: dict | None, *, user_id, thresholds, objective_statements) -> QuestionResult:
    if q.type in ("mcq", "multi_select"):
        return grade_choice(q, answer)
    if q.type == "numeric":
        return grade_numeric(q, answer)
    if q.type == "code":
        return grade_code_question(q, answer, user_id=user_id, thresholds=thresholds)
    return grade_rubric(q, answer, user_id=user_id, thresholds=thresholds, objective_statements=objective_statements)


@dataclass
class Decision:
    score: float
    passed: bool
    needs_review: bool
    category_scores: dict[str, float]
    objective_scores: dict[str, float]
    critical_failures: list[str]
    reasons: list[str]


def decide(results: list[QuestionResult], threshold: float, thresholds: ProgressionThresholds, critical_objectives: set[str]) -> Decision:
    counted = [r for r in results if r.required]
    total = sum(r.max_score for r in counted)
    score = sum(r.score for r in counted) / total if total else 0.0
    reasons: list[str] = []
    unanswered = [r.question_key for r in counted if not r.answered]
    if unanswered:
        reasons.append(f"Required questions not answered: {', '.join(unanswered)}")
    if score < threshold:
        reasons.append(f"Overall score {score:.0%} is below the {threshold:.0%} threshold.")
    cats: dict[str, list[float]] = {}
    for r in counted:
        key = "conceptual" if r.category == "recall" else r.category
        cats.setdefault(key, [0.0, 0.0])
        cats[key][0] += r.score
        cats[key][1] += r.max_score
    category_scores = {k: (v[0] / v[1] if v[1] else 0.0) for k, v in cats.items()}
    for cat, s in category_scores.items():
        if s < thresholds.category(cat):
            reasons.append(f"{cat.capitalize()} score {s:.0%} is below the {thresholds.category(cat):.0%} threshold.")
    obj: dict[str, list[float]] = {}
    for r in counted:
        for o in r.objective_ids:
            obj.setdefault(o, [0.0, 0.0])
            obj[o][0] += r.score
            obj[o][1] += r.max_score
    objective_scores = {k: (v[0] / v[1] if v[1] else 0.0) for k, v in obj.items()}
    critical_failures = sorted(o for o in critical_objectives if o in objective_scores and objective_scores[o] < thresholds.critical_objective)
    for r in counted:  # a critical question missing a required-for-mastery idea fails its objectives
        if r.critical and r.grader == "rubric_llm" and not r.meets_mastery:
            for o in r.objective_ids:
                if o in critical_objectives and o not in critical_failures:
                    critical_failures.append(o)
    if critical_failures:
        reasons.append("Critical objectives below mastery: " + ", ".join(sorted(critical_failures)))
    needs_review = any(r.review_status == "flagged" for r in results)
    if needs_review:
        reasons.append("One or more answers were flagged for manual review because two independent gradings disagreed.")
    passed = not reasons
    return Decision(score, passed, needs_review, category_scores, objective_scores, sorted(set(critical_failures)), reasons)


def grade_submission(db: Session, submission: Submission) -> Grade:
    settings = get_settings()
    thresholds = settings.thresholds
    assessment = db.get(Assessment, submission.assessment_id)
    answers = {a.question_key: a.payload for a in submission.artifacts}
    keys = {k for row in assessment.questions for k in row.objective_keys}
    objectives = db.scalars(select(LearningObjective).where(LearningObjective.key.in_(keys))).all() if keys else []
    statements = {o.key: o.statement for o in objectives}
    critical = {o.key for o in objectives if o.critical} | {k for row in assessment.questions if row.critical for k in row.objective_keys}

    results: list[QuestionResult] = []
    for row in assessment.questions:
        q = Question.model_validate(row.content)
        res = grade_question(q, answers.get(row.question_key), user_id=submission.user_id, thresholds=thresholds, objective_statements=statements)
        res.required = row.required
        res.rubric_id = row.rubric_id
        res.details["qtype"] = q.type
        results.append(res)

    decision = decide(results, assessment.pass_threshold, thresholds, critical)
    grade = Grade(
        submission_id=submission.id, score=decision.score, passed=decision.passed and not decision.needs_review,
        category_scores=decision.category_scores, objective_scores=decision.objective_scores,
        critical_failures=decision.critical_failures, failure_reasons=decision.reasons,
        summary=_summary(decision), needs_review=decision.needs_review, grader_version=GRADER_VERSION,
    )
    db.add(grade)
    db.flush()
    for r in results:
        db.add(RubricResult(
            grade_id=grade.id, question_key=r.question_key, rubric_id=r.rubric_id, grader=r.grader, score=r.score,
            max_score=r.max_score, criteria=r.criteria, confidence=r.confidence, correct_concepts=r.correct_concepts,
            missing_concepts=r.missing_concepts, incorrect_claims=r.incorrect_claims, misconceptions=r.misconceptions,
            feedback=r.feedback, next_steps=r.next_steps, meets_mastery=r.meets_mastery, review_status=r.review_status,
            details=r.details | {"category": r.category, "objective_ids": r.objective_ids, "critical": r.critical,
                                 "required": r.required, "answered": r.answered},
            ai_call_ids=r.ai_call_ids,
        ))
    submission.status = "needs_review" if decision.needs_review else "graded"
    submission.graded_at = utcnow()
    db.flush()
    return grade


def _summary(d: Decision) -> str:
    if d.needs_review:
        return f"Score {d.score:.0%}. Awaiting manual review of flagged answers before a pass/fail decision."
    if d.passed:
        return f"Passed with {d.score:.0%}. Every critical objective met the mastery bar."
    return f"Not yet passed ({d.score:.0%}). " + " ".join(d.reasons)
