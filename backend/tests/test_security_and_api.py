from app.services import jobs
from tests.conftest import onboard, register
from tests.helpers import answers, lesson_id_by_key, submit


def test_requires_auth(client):
    for path in ["/api/dashboard", "/api/curriculum", "/api/settings", "/api/admin/costs"]:
        assert client.get(path).status_code == 401


def test_password_and_duplicate_rules(client):
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422
    register(client, "a@example.com")
    assert client.post("/api/auth/register", json={"email": "A@example.com", "password": "another long password"}).status_code == 409
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct horse battery"}).status_code == 200


def test_first_user_is_admin_second_is_not(client):
    assert register(client)["is_admin"] is True
    client.post("/api/auth/logout")
    assert register(client)["is_admin"] is False
    assert client.get("/api/admin/costs").status_code == 403


def test_cross_user_isolation(client):
    register(client)
    onboard(client)
    jobs.drain()
    l1 = lesson_id_by_key("b01.m01.l01")
    aid = client.get(f"/api/lessons/{l1}").json()["assessment"]["id"]
    submit(client, aid, answers(aid), test_out=False)
    client.post("/api/auth/logout")
    register(client)
    assert client.get(f"/api/assessments/{aid}").status_code == 404
    assert submit(client, aid, {}).status_code == 404


def test_lesson_payload_contains_no_answers(client):
    register(client)
    onboard(client)
    jobs.drain()
    l5_blob = client.get(f"/api/lessons/{lesson_id_by_key('b01.m01.l01')}").text
    for secret in ("reference_solution", "hidden_tests", "correct_option_ids", "reference_answer", "variant_bank"):
        assert secret not in l5_blob
    aid = client.get(f"/api/lessons/{lesson_id_by_key('b01.m01.l01')}").json()["assessment"]["id"]
    assert "grading" not in client.get(f"/api/assessments/{aid}").text


def test_locked_lessons_hide_content(client):
    register(client)
    onboard(client)
    l3 = client.get(f"/api/lessons/{lesson_id_by_key('b01.m02.l03')}").json()
    assert l3["state"] == "locked" and "content" not in l3 and "locked_reason" in l3


def test_submission_idempotency(client):
    register(client)
    onboard(client)
    jobs.drain()
    l1 = lesson_id_by_key("b01.m01.l01")
    lesson = client.get(f"/api/lessons/{l1}").json()
    for sid in lesson["content"]["completion"]["required_section_ids"]:
        client.post(f"/api/lessons/{l1}/sections/{sid}/complete", json={"version_id": lesson["version_id"]})
    body = {"answers": answers(lesson["assessment"]["id"]), "idempotency_key": "same-key-123"}
    a = client.post(f"/api/assessments/{lesson['assessment']['id']}/submissions", json=body).json()
    b = client.post(f"/api/assessments/{lesson['assessment']['id']}/submissions", json=body).json()
    assert a["submission_id"] == b["submission_id"] and b["duplicate"]


def test_unsubscribe(client, outbox):
    register(client)
    from app.db import SessionLocal
    from app.models import UserPreferences

    with SessionLocal() as s:
        token = s.query(UserPreferences).first().unsubscribe_token
    assert client.get(f"/api/email/unsubscribe?token={token}").status_code == 200
    assert client.get("/api/settings").json()["email_enabled"] is False


def test_tutor_streams_and_persists(client):
    register(client)
    onboard(client)
    jobs.drain()
    l1 = lesson_id_by_key("b01.m01.l01")
    cid = client.post("/api/tutor/conversations", json={"lesson_id": l1, "mode": "socratic"}).json()["id"]
    with client.stream("POST", f"/api/tutor/conversations/{cid}/messages", json={"message": "Why is cos 90 zero?", "mode": "socratic"}) as r:
        body = "".join(r.iter_text())
    assert "event: delta" in body and "event: done" in body
    convs = client.get(f"/api/tutor/conversations?lesson_id={l1}").json()
    assert [m["role"] for m in convs[0]["messages"]] == ["user", "assistant"]
