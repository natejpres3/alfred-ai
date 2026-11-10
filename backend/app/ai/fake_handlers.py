"""Deterministic stand-ins for each LLM role. Used by tests and AI_PROVIDER=fake.

The fake rubric grader is a keyword-overlap heuristic: good enough to exercise every code path
(pass, fail, borderline second pass), useless as a real grader — which is why the UI labels
fake-graded results.
"""

from __future__ import annotations

import re

STOP = {
    "the", "and", "that", "this", "with", "from", "into", "their", "there", "which", "when",
    "what", "have", "will", "your", "about", "each", "then", "than", "they", "them", "also",
    "student", "explains", "explain", "states", "state", "correctly", "answer", "uses", "shows",
    "does", "should", "must", "would", "could", "only", "more", "most", "some", "such",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text.lower()) if t not in STOP}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text.lower())).strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?\n])\s+", text) if s.strip()]


def rubric_grade(system: str, prompt: str, ctx: dict) -> dict:
    answer: str = ctx.get("answer", "")
    rubric: dict = ctx.get("rubric", {"criteria": []})
    ans_tokens = _tokens(answer)
    criteria = []
    correct, missing = [], []
    for c in rubric["criteria"]:
        keys = _tokens(c["description"])
        if keys:
            overlap = len(keys & ans_tokens) / len(keys)
        else:  # symbolic criterion (e.g. "dL/da = 2(a − y)"): require it verbatim, modulo spacing/punctuation
            overlap = 1.0 if _norm(c["description"]) and _norm(c["description"]) in _norm(answer) else 0.0
        frac = 1.0 if overlap >= 0.34 else 0.5 if overlap >= 0.15 else 0.0
        evidence = []
        if frac > 0:
            for s in _sentences(answer):
                if (_tokens(s) & keys) or (not keys and _norm(c["description"]) in _norm(s)):
                    evidence.append(s)
                    break
        criteria.append(
            {
                "criterion_id": c["id"],
                "points_awarded": round(c["points"] * frac, 3),
                "evidence": evidence,
                "rationale": f"[offline heuristic] keyword overlap {overlap:.2f}",
            }
        )
        (correct if frac == 1.0 else missing).append(c["description"])
    return {
        "criteria": criteria,
        "correct_concepts": correct,
        "missing_concepts": missing,
        "incorrect_claims": [],
        "misconceptions": [f"Incomplete understanding: {m}" for m in missing[:2]],
        "feedback": "[Offline heuristic grader] " + (
            "Your answer covers the rubric's key ideas." if not missing else
            "Your answer is missing: " + "; ".join(missing)
        ),
        "next_steps": ["Re-read the relevant section and restate the missing ideas in your own words."] if missing else [],
        "confidence": 0.9,
    }


def code_review(system: str, prompt: str, ctx: dict) -> dict:
    return {
        "implements_required_algorithm": not ctx.get("static_violations"),
        "algorithm_assessment": "[offline] Static checks only.",
        "correctness_notes": [],
        "quality_notes": [],
        "edge_cases_missed": [],
        "feedback": "[Offline code review] Automated tests determine correctness; no qualitative review was performed.",
        "next_steps": [],
        "confidence": 0.5,
    }


def lesson_review(system: str, prompt: str, ctx: dict) -> dict:
    return {
        "verdict": "approve",
        "mathematically_correct": True,
        "objectives_aligned": True,
        "appropriate_level": True,
        "issues": [],
        "summary": "[offline] Not reviewed.",
    }


def diagnosis(system: str, prompt: str, ctx: dict) -> dict:
    return {
        "objectives": [
            {
                "objective_id": o,
                "likely_misconception": "Could not be diagnosed offline.",
                "evidence": "",
                "prerequisite_gap": None,
            }
            for o in ctx.get("failed_objectives", [])
        ],
        "recommended_strategy": "worked-examples",
    }


def remediation_content(system: str, prompt: str, ctx: dict) -> dict:
    failed = ctx.get("failed_objectives", [])
    statements = ctx.get("objective_statements", {})
    variants = ctx.get("variant_questions", [])
    used = set(ctx.get("used_strategies", []))
    strategy = next(s for s in ["worked-examples", "contrast-cases", "first-principles-rederivation", "analogy"] if s not in used) if len(used) < 4 else "worked-examples"
    bullet = "\n".join(f"- **{o}**: {statements.get(o, '')}" for o in failed)
    return {
        "strategy": strategy,
        "title": "Targeted review",
        "diagnosis_summary": "These objectives were below the mastery threshold:\n" + bullet,
        "sections": [
            {
                "id": "rem-1",
                "kind": "remediation",
                "title": "Revisit the key ideas",
                "estimated_minutes": 10,
                "required": True,
                "blocks": [
                    {"type": "markdown", "text": "[Offline remediation] Review the following objectives, then answer the new questions.\n\n" + bullet},
                    *[{"type": "markdown", "text": e} for e in ctx.get("explanations", [])],
                ],
            },
            {
                "id": "rem-2",
                "kind": "recall",
                "title": "Check your understanding",
                "estimated_minutes": 10,
                "required": True,
                "blocks": [{"type": "question", "question_id": q["id"]} for q in variants],
            },
        ],
        "questions": variants,
        "resources": [],
    }


def lesson_content(system: str, prompt: str, ctx: dict) -> dict:
    spec = ctx["spec"]
    objectives = spec["objectives"]
    qs = []
    for i, o in enumerate(objectives, 1):
        qs.append(
            {
                "id": f"q{i}",
                "type": "short_answer",
                "category": "conceptual",
                "prompt": f"In your own words: {o['statement']}",
                "objective_ids": [o["key"]],
                "critical": bool(o.get("critical")),
                "required": True,
                "points": 1.0,
                "options": None,
                "code": None,
                "hints": [],
                "grading": {
                    "rubric": {
                        "criteria": [{"id": "c1", "description": o["statement"], "points": 1.0, "required_for_mastery": True}],
                        "reference_answer": o["statement"],
                        "common_misconceptions": [],
                    },
                    "explanation": "Offline placeholder lesson — no worked explanation available.",
                },
            }
        )
    return {
        "lesson_key": spec["key"],
        "title": spec["title"],
        "subtitle": "Offline placeholder",
        "summary": f"Placeholder generated without an AI provider for: {spec['title']}.",
        "why_it_matters": "Configure AI_PROVIDER=anthropic to generate the real lesson.",
        "explanation_strategy": "placeholder",
        "objectives": [
            {"id": o["key"], "statement": o["statement"], "concept_key": o["concept"], "critical": bool(o.get("critical")), "bloom": "understand"}
            for o in objectives
        ],
        "prerequisites": ctx.get("prerequisites", []),
        "connections": [],
        "estimated_minutes": 20,
        "sections": [
            {
                "id": "s1",
                "kind": "concept",
                "title": spec["title"],
                "estimated_minutes": 10,
                "required": True,
                "blocks": [{"type": "markdown", "text": "**Offline placeholder.** This lesson would be generated by the Lesson Author."}],
            },
            {
                "id": "s2",
                "kind": "recall",
                "title": "Active recall",
                "estimated_minutes": 10,
                "required": True,
                "blocks": [{"type": "question", "question_id": q["id"]} for q in qs],
            },
        ],
        "questions": qs,
        "resources": [],
        "homework": [],
        "completion": {"required_section_ids": ["s1", "s2"], "required_question_ids": [q["id"] for q in qs], "pass_threshold": 0.85},
        "variant_bank": [],
    }


def resource_candidates(system: str, prompt: str, ctx: dict) -> dict:
    return {"resources": []}


DEFAULT_HANDLERS = {
    "RubricGrade": rubric_grade,
    "CodeReview": code_review,
    "LessonReview": lesson_review,
    "Diagnosis": diagnosis,
    "RemediationContent": remediation_content,
    "LessonContent": lesson_content,
    "ResourceCandidates": resource_candidates,
}
