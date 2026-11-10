"""Test helpers: build perfect / wrong answers from the grader-side content and drive the API."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Assessment, AssessmentQuestion
from app.services import jobs


def assessment_rows(assessment_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        return [r.content for r in db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment_id)
                                              .order_by(AssessmentQuestion.position))]
    finally:
        db.close()


def perfect_answer(q: dict) -> dict:
    g = q["grading"]
    if q["type"] in ("mcq", "multi_select"):
        return {"selected": g["correct_option_ids"]}
    if q["type"] == "numeric":
        return {"value": str(g["numeric"]["value"])}
    if q["type"] == "code":
        return {"code": g["code"]["reference_solution"]}
    # rubric: the reference answer plus every criterion restated satisfies the offline grader
    text = g["rubric"]["reference_answer"] + "\n" + "\n".join(c["description"] + "." for c in g["rubric"]["criteria"])
    return {"text": text}


def wrong_answer(q: dict) -> dict:
    if q["type"] in ("mcq", "multi_select"):
        wrong = [o["id"] for o in q["options"] if o["id"] not in q["grading"]["correct_option_ids"]]
        return {"selected": wrong[:1]}
    if q["type"] == "numeric":
        return {"value": str(q["grading"]["numeric"]["value"] + 123)}
    if q["type"] == "code":
        return {"code": q["code"]["starter_code"] + "\n# attempted\n"}
    return {"text": "I am not sure about this one."}


def answers(assessment_id: str, mode="perfect", overrides: dict | None = None) -> dict:
    out = {}
    for q in assessment_rows(assessment_id):
        out[q["id"]] = (perfect_answer if mode == "perfect" else wrong_answer)(q)
    out.update(overrides or {})
    return out


def complete_sections(client, lesson_id: str, version_id: str, section_ids: list[str]) -> None:
    for sid in section_ids:
        r = client.post(f"/api/lessons/{lesson_id}/sections/{sid}/complete", json={"version_id": version_id})
        assert r.status_code == 200, r.text


def submit(client, assessment_id: str, ans: dict, test_out: bool = False):
    return client.post(f"/api/assessments/{assessment_id}/submissions",
                       json={"answers": ans, "idempotency_key": uuid.uuid4().hex, "test_out": test_out})


def pass_lesson(client, lesson_id: str) -> dict:
    """Open a prepared lesson, complete all sections, submit perfect answers, run jobs. Returns the submission view."""
    jobs.drain()
    lesson = client.get(f"/api/lessons/{lesson_id}").json()
    assert lesson.get("content"), lesson
    client.post(f"/api/lessons/{lesson_id}/start")
    complete_sections(client, lesson_id, lesson["version_id"], lesson["content"]["completion"]["required_section_ids"])
    r = submit(client, lesson["assessment"]["id"], answers(lesson["assessment"]["id"]))
    assert r.status_code == 200, r.text
    jobs.drain()
    view = client.get(f"/api/submissions/{r.json()['submission_id']}").json()
    assert view["grade"]["passed"], view["grade"]
    return view


def lesson_id_by_key(key: str) -> str:
    from app.models import Lesson

    db = SessionLocal()
    try:
        return db.scalar(select(Lesson.id).where(Lesson.key == key))
    finally:
        db.close()


def assessment(assessment_id: str) -> Assessment:
    db = SessionLocal()
    try:
        return db.get(Assessment, assessment_id)
    finally:
        db.close()
