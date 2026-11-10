import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.models import Grade
from app.services import jobs
from tests.conftest import onboard, register
from tests.helpers import answers, complete_sections, lesson_id_by_key, submit

BACKEND = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_matches_models():
    with tempfile.TemporaryDirectory() as d:
        env = os.environ | {"DATABASE_URL": f"sqlite:///{d}/m.db"}
        up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr
        check = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND, env=env, capture_output=True, text=True)
        assert check.returncode == 0, check.stdout + check.stderr


def test_admin_override_supersedes_grade_and_advances(client, fake_ai, db):
    register(client)  # first user → admin
    onboard(client)
    jobs.drain()
    l1 = lesson_id_by_key("b01.m01.l01")
    lesson = client.get(f"/api/lessons/{l1}").json()
    complete_sections(client, l1, lesson["version_id"], lesson["content"]["completion"]["required_section_ids"])

    # graders disagree → flagged → lesson waits for manual review
    def disagree(s, p, c):
        pts = 0 if c["pass"] == 1 else 10
        return {"criteria": [{"criterion_id": cr["id"], "points_awarded": pts, "evidence": [c["answer"][:20]], "rationale": ""}
                             for cr in c["rubric"]["criteria"]],
                "correct_concepts": [], "missing_concepts": [], "incorrect_claims": [], "misconceptions": [], "feedback": "",
                "next_steps": [], "confidence": 0.4}
    fake_ai.handlers["RubricGrade"] = disagree
    sid = submit(client, lesson["assessment"]["id"], answers(lesson["assessment"]["id"])).json()["submission_id"]
    jobs.drain()
    view = client.get(f"/api/submissions/{sid}").json()
    assert view["grade"]["needs_review"] and view["status"] == "needs_review"
    assert client.get(f"/api/lessons/{l1}").json()["state"] == "grading"
    queue = client.get("/api/admin/review-queue").json()
    assert queue["flagged"] and queue["flagged"][0]["submission_id"] == sid

    r = client.post(f"/api/admin/grades/{view['grade']['id']}/override", json={"passed": True, "note": "Answers are correct."})
    assert r.status_code == 200, r.text
    jobs.drain()
    assert client.get(f"/api/lessons/{l1}").json()["state"] == "passed"
    grades = db.scalars(select(Grade).order_by(Grade.created_at)).all()
    assert grades[0].superseded_by_id == grades[1].id and grades[1].created_by == "admin"
