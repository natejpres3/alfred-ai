from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.provider import AIInvalidOutput, AIRefusal, AnthropicProvider, BudgetExceeded
from app.config import get_settings
from app.models import AICall


class Out(BaseModel):
    answer: str


def _message(stop_reason="end_turn", text='{"answer": "42"}'):
    return SimpleNamespace(
        stop_reason=stop_reason, stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0),
        model="claude-opus-5-5", _request_id="req_123",
    )


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


@pytest.fixture()
def provider(engine, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = AnthropicProvider()
    p.captured = {}

    def make(msg):
        def stream(**kw):
            p.captured = kw
            return FakeStream(msg)
        p.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)),
                                   messages=SimpleNamespace(stream=stream))
    p.make = make
    return p


def test_structured_success_logs_cost_and_sends_expected_request(provider, db):
    provider.make(_message())
    res = provider.structured(role="grader", system="sys", prompt="hi", schema=Out)
    assert res.value.answer == "42"
    kw = provider.captured
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"]["effort"] == "high" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in kw
    call = db.scalar(select(AICall).where(AICall.id == res.call_id))
    assert call.status == "ok" and call.cost_usd == pytest.approx((1000 * 4 + 500 * 20) / 1e6) and call.request_id == "req_123"


@pytest.mark.parametrize("msg,exc,status", [(_message("refusal"), AIRefusal, "refusal"),
                                            (_message("max_tokens"), AIInvalidOutput, "invalid"),
                                            (_message(text='{"wrong": 1}'), AIInvalidOutput, "invalid")])
def test_structured_failures(provider, db, msg, exc, status):
    provider.make(msg)
    with pytest.raises(exc):
        provider.structured(role="grader", system="s", prompt="p", schema=Out)
    assert db.scalar(select(AICall.status).order_by(AICall.created_at.desc())) == status


def test_refusal_is_not_retried():
    assert AIRefusal.retryable is False and BudgetExceeded.retryable is False


def test_budget_guard(provider, db, monkeypatch):
    db.add(AICall(role="author", model="claude-opus-5-5", status="ok", prompt_hash="x", cost_usd=get_settings().ai_monthly_budget_usd + 1))
    db.commit()
    provider.make(_message())
    with pytest.raises(BudgetExceeded):
        provider.structured(role="grader", system="s", prompt="p", schema=Out)
