"""End-to-end: the full MVP learning lifecycle through the HTTP API (docs/01 §7)."""

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import BackgroundJob, EmailDelivery, Notification, RemediationPlan
from app.services import jobs
from app.services.workflow import job_grade_submission, job_prepare_lesson
from tests.conftest import onboard, register
from tests.helpers import answers, complete_sections, lesson_id_by_key, pass_lesson, submit


def _emails(outbox, subject_part):
    return [m for m in outbox if subject_part in m.subject]


def test_full_learning_lifecycle(client, outbox):
    register(client)
    onboard(client)
    jobs.drain()

    # first lesson prepared and emailed exactly once
    l1 = lesson_id_by_key("b01.m01.l01")
    assert len(_emails(outbox, "Your next lesson is ready: Vectors, dot products")) == 1
    lesson = client.get(f"/api/lessons/{l1}").json()
    assert lesson["state"] == "available" and lesson["content"]["title"].startswith("Vectors")
    aid = lesson["assessment"]["id"]

    # cannot submit before completing required sections
    r = submit(client, aid, answers(aid))
    assert r.status_code == 422 and "missing_sections" in r.json()["detail"]

    client.post(f"/api/lessons/{l1}/start")
    complete_sections(client, l1, lesson["version_id"], lesson["content"]["completion"]["required_section_ids"])

    # fail: everything right except the critical free-response explanations
    ans = answers(aid)
    for qid in ("q3", "q5", "q7"):
        ans[qid] = {"text": "I am not sure."}
    r = submit(client, aid, ans)
    assert r.status_code == 200
    jobs.drain()
    sub = client.get(f"/api/submissions/{r.json()['submission_id']}").json()
    g = sub["grade"]
    assert g["passed"] is False
    assert "b01.m01.l01.o2" in g["critical_failures"]
    q3 = next(q for q in sub["grade"]["questions"] if q["key"] == "q3")
    assert q3["criteria"] and q3["feedback"] and q3["meets_mastery"] is False

    # remediation generated with new, distinct questions; lesson state reflects it
    lesson = client.get(f"/api/lessons/{l1}").json()
    assert lesson["state"] == "remediation_required"
    rem = lesson["remediation"]
    assert rem["content"]["questions"], rem
    original_prompts = {q["prompt"] for q in client.get(f"/api/assessments/{aid}").json()["questions"]}
    rem_aid = lesson["assessment"]["id"]
    assert rem_aid != aid and lesson["assessment"]["kind"] == "remediation"
    rem_questions = client.get(f"/api/assessments/{rem_aid}").json()["questions"]
    new_items = [q for q in rem_questions if q["prompt"] not in original_prompts]
    assert new_items, "remediation must include questions the student has not seen"
    assert len(_emails(outbox, "Targeted review ready")) == 1

    # the old assessment can no longer be submitted
    assert submit(client, aid, answers(aid)).status_code == 409

    # pass the remediation
    complete_sections(client, l1, rem["version_id"], rem["content"]["completion"]["required_section_ids"])
    r = submit(client, rem_aid, answers(rem_aid))
    assert r.status_code == 200, r.text
    jobs.drain()
    sub = client.get(f"/api/submissions/{r.json()['submission_id']}").json()
    assert sub["grade"]["passed"], sub["grade"]["failure_reasons"]

    lesson = client.get(f"/api/lessons/{l1}").json()
    assert lesson["state"] == "passed"

    # next lesson unlocked, prepared and emailed exactly once
    l2 = lesson_id_by_key("b01.m01.l02")
    assert client.get(f"/api/lessons/{l2}").json()["state"] == "available"
    assert len(_emails(outbox, "Your next lesson is ready: Matrix multiplication")) == 1

    # replaying jobs must not duplicate anything
    db = SessionLocal()
    try:
        for job in db.scalars(select(BackgroundJob).where(BackgroundJob.kind.in_(["grade_submission", "prepare_lesson"]))).all():
            with SessionLocal() as s:
                (job_grade_submission if job.kind == "grade_submission" else job_prepare_lesson)(s, job.payload)
                s.commit()
        jobs.drain()
        assert db.scalar(select(func.count(Notification.id)).where(Notification.kind == "lesson_available")) == 2
        assert db.scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.status == "sent",
                                                                    EmailDelivery.subject.like("Your next lesson%"))) == 2
        assert db.scalar(select(func.count(RemediationPlan.id))) == 1
    finally:
        db.close()

    # dashboard reflects progress, mastery, history
    dash = client.get("/api/dashboard").json()
    assert dash["progress"]["lessons_passed"] == 1
    assert dash["current"]["lesson_id"] == l2
    assert {c["key"] for c in dash["mastered"]} >= {"la.dot_product"}
    assert dash["recent_grades"][0]["passed"] is True


def test_module_gate_requires_checkpoint_and_project(client, outbox):
    register(client)
    onboard(client)
    for key in ("b01.m01.l01", "b01.m01.l02", "b01.m02.l03", "b01.m03.l04", "b01.m03.l05"):
        pass_lesson(client, lesson_id_by_key(key))

    checkpoint = lesson_id_by_key("b01.m03.checkpoint")
    jobs.drain()
    assert client.get(f"/api/lessons/{checkpoint}").json()["state"] == "available"
    pass_lesson(client, checkpoint)

    # all lessons passed but the project gate is still closed
    roadmap = client.get("/api/curriculum").json()
    m03 = next(m for m in roadmap["blocks"][0]["modules"] if m["key"] == "b01.m03")
    m04 = next(m for m in roadmap["blocks"][0]["modules"] if m["key"] == "b01.m04")
    assert m03["state"] == "project_pending"
    assert m04["state"] == "locked"

    project = client.get("/api/projects/gd_linreg").json()
    assert not project["passed"] and len(project["milestones"]) == 3

    # a closed-form shortcut is capped by static checks, even if tests pass
    from app.db import SessionLocal as S
    from app.models import ProjectMilestone

    with S() as s:
        specs = {m.key: m.spec for m in s.scalars(select(ProjectMilestone))}
    cheat = specs["m3"]["reference_solution"].replace(
        "def train(X, y, lr=0.1, epochs=200, batch_size=None, seed=0):",
        "def train(X, y, lr=0.1, epochs=200, batch_size=None, seed=0):\n"
        "    A = np.c_[X, np.ones(len(y))]\n    sol = np.linalg.lstsq(A, y, rcond=None)[0]\n    return sol[:-1], float(sol[-1]), [0.0] * epochs\n"
        "\ndef _unused(X, y, lr=0.1, epochs=200, batch_size=None, seed=0):")
    m3 = next(m for m in project["milestones"] if m["key"] == "m3")
    client.post(f"/api/projects/milestones/{m3['id']}/submissions", json={"source": "editor", "code": cheat})
    jobs.drain()
    project = client.get("/api/projects/gd_linreg").json()
    m3v = next(m for m in project["milestones"] if m["key"] == "m3")
    assert m3v["best_score"] <= 0.5 and "not allowed" in m3v["submissions"][0]["feedback"]

    for ms in project["milestones"]:
        r = client.post(f"/api/projects/milestones/{ms['id']}/submissions", json={"source": "editor", "code": specs[ms["key"]]["reference_solution"]})
        assert r.status_code == 200
    jobs.drain()
    project = client.get("/api/projects/gd_linreg").json()
    assert project["passed"], project

    roadmap = client.get("/api/curriculum").json()
    mods = {m["key"]: m for m in roadmap["blocks"][0]["modules"]}
    assert mods["b01.m03"]["state"] == "completed"
    assert mods["b01.m04"]["state"] in ("available", "in_progress")
    assert _emails(outbox, "Module complete: Optimization Foundations")
    assert _emails(outbox, "Unlocked: Vector Spaces and Geometry")

    # the first un-authored lesson is generated on demand (fake author → offline placeholder) and validated
    gen = client.get(f"/api/lessons/{lesson_id_by_key('b01.m04.l01')}").json()
    assert gen["state"] == "available" and gen["source"] == "generated"
    assert {o["id"] for o in gen["content"]["objectives"]} == {"b01.m04.l01.o1", "b01.m04.l01.o2"}


def test_test_out_after_diagnostic(client):
    register(client)
    client.post("/api/onboarding/profile", json={"background": {"math": 4, "programming": 4, "ml": 2, "ai": 2},
                                                  "timezone": "UTC"})
    did = client.post("/api/onboarding/diagnostic").json()["assessment_id"]
    from tests.helpers import answers as mk

    r = submit(client, did, mk(did))
    assert r.status_code == 200
    jobs.drain()
    client.post("/api/onboarding/complete")
    jobs.drain()
    l1 = lesson_id_by_key("b01.m01.l01")
    lesson = client.get(f"/api/lessons/{l1}").json()
    assert lesson["test_out_eligible"] is True
    # test-out skips section completion but still requires passing the real assessment
    r = submit(client, lesson["assessment"]["id"], answers(lesson["assessment"]["id"]), test_out=True)
    assert r.status_code == 200
    jobs.drain()
    assert client.get(f"/api/lessons/{l1}").json()["state"] == "passed"
