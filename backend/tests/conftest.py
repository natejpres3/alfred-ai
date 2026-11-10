import os
import tempfile
import uuid

os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "sqlite://"),
    AI_PROVIDER="fake",
    SANDBOX_BACKEND="unsafe-local",
    SANDBOX_ALLOW_UNSAFE_LOCAL="true",
    EMAIL_PROVIDER="console",
    OUTBOX_DIR=tempfile.mkdtemp(prefix="academy-outbox-"),
    AI_MONTHLY_BUDGET_USD="1000",
    PUBLIC_WEB_URL="http://testserver",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401

# Resource link checks hit the network; tests stub them unless explicitly enabled.
import app.services.resources as resources  # noqa: E402
from app import db as dbmod  # noqa: E402
from app.ai.provider import FakeProvider, set_provider  # noqa: E402
from app.email.providers import ConsoleProvider  # noqa: E402
from app.services import workflow  # noqa: E402,F401
from app.services.curriculum import sync_curriculum  # noqa: E402

resources.check_url = lambda url, claimed_title="", client=None: ("verified", 200, {"stub": True})


@pytest.fixture()
def engine():
    eng = dbmod.configure(os.environ["DATABASE_URL"])
    dbmod.Base.metadata.drop_all(eng)
    dbmod.Base.metadata.create_all(eng)
    with dbmod.session_scope() as s:
        sync_curriculum(s)
    yield eng
    dbmod.Base.metadata.drop_all(eng)


@pytest.fixture()
def db(engine):
    s = dbmod.SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def fake_ai(engine):
    p = FakeProvider()
    set_provider(p)
    yield p
    set_provider(None)


@pytest.fixture()
def outbox():
    ConsoleProvider.sent.clear()
    yield ConsoleProvider.sent
    ConsoleProvider.sent.clear()


@pytest.fixture()
def client(engine, fake_ai, outbox):
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def register(client, email=None, password="correct horse battery"):
    email = email or f"student-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "Student"})
    assert r.status_code == 200, r.text
    return r.json()


def onboard(client, **prefs):
    body = {"background": {"math": 2, "programming": 3, "ml": 1, "ai": 1, "notes": ""}, "goals": "mastery",
            "daily_goal_minutes": 60, "timezone": "America/Chicago", "delivery_mode": "immediate", "delivery_hour": 7} | prefs
    assert client.post("/api/onboarding/profile", json=body).status_code == 200
    return client.post("/api/onboarding/complete").json()
