"""LLM provider abstraction.

Every role (author, grader, tutor, …) calls `get_provider().structured(...)` or
`.stream_text(...)`. Providers:

* AnthropicProvider — Claude via the official SDK, structured outputs, adaptive thinking,
  server-side refusal fallbacks, prompt caching on the system prompt.
* FakeProvider — deterministic, offline. Used in tests and when AI_PROVIDER=fake. Its output is
  clearly labelled and must never be mistaken for real grading.

Every call is logged to `ai_calls` (tokens, cost, latency, prompt hash) in its own transaction
so failures are recorded even when the caller's transaction rolls back.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.costs import estimate_cost, month_to_date_spend
from app.ai.schema_utils import strict_json_schema
from app.config import get_settings
from app.db import session_scope

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    retryable = True


class BudgetExceeded(AIError):
    retryable = False


class AIRefusal(AIError):
    retryable = False


class AIInvalidOutput(AIError):
    pass


class AIUnavailable(AIError):
    pass


@dataclass
class AIResult(Generic[T]):
    value: T
    call_id: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def structured(
        self,
        *,
        role: str,
        system: str,
        prompt: str,
        schema: type[T],
        user_id: str | None = None,
        context: dict | None = None,
    ) -> AIResult[T]: ...

    def stream_text(
        self,
        *,
        role: str,
        system: str,
        messages: list[dict],
        user_id: str | None = None,
        context: dict | None = None,
    ) -> Iterator[str]: ...


def _prompt_hash(system: str, payload: Any) -> str:
    return hashlib.sha256((system + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()


def _log_call(**fields) -> str:
    from app.models import AICall

    with session_scope() as db:
        call = AICall(**fields)
        db.add(call)
        db.flush()
        return call.id


def _check_budget() -> None:
    settings = get_settings()
    with session_scope() as db:
        spent = month_to_date_spend(db)
    if spent >= settings.ai_monthly_budget_usd:
        raise BudgetExceeded(
            f"Monthly AI budget of ${settings.ai_monthly_budget_usd:.2f} reached (spent ${spent:.2f}). "
            "Raise AI_MONTHLY_BUDGET_USD to continue."
        )


# --------------------------------------------------------------------------- Anthropic


class AnthropicProvider:
    name = "anthropic"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=3)
        self.settings = get_settings()

    def _request(self, role: str, system: str, messages: list[dict], output_format: dict | None):
        cfg = self.settings.role(role)
        output_config: dict[str, Any] = {"effort": cfg.effort}
        if output_format:
            output_config["format"] = output_format
        kwargs: dict[str, Any] = dict(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            thinking={"type": "adaptive"},
            output_config=output_config,
        )
        if self.settings.ai_enable_fallbacks:
            return cfg, self.client.beta.messages.stream(
                **kwargs, betas=[self.FALLBACK_BETA], fallbacks="default"
            )
        return cfg, self.client.messages.stream(**kwargs)

    def _usage_fields(self, model: str, usage) -> dict:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return dict(
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cr,
            cache_write_tokens=cw,
            cost_usd=estimate_cost(model, inp, out, cr, cw),
        )

    def structured(self, *, role, system, prompt, schema, user_id=None, context=None):
        _check_budget()
        anthropic = self._anthropic
        messages = [{"role": "user", "content": prompt}]
        phash = _prompt_hash(system, messages)
        cfg, stream_mgr = self._request(
            role, system, messages, {"type": "json_schema", "schema": strict_json_schema(schema)}
        )
        started = time.monotonic()
        base = dict(role=role, model=cfg.model, user_id=user_id, prompt_hash=phash, context=context or {})
        try:
            with stream_mgr as stream:
                message = stream.get_final_message()
        except anthropic.RateLimitError as e:
            _log_call(**base, status="error", error=f"rate_limited: {e}", latency_ms=_ms(started))
            raise AIUnavailable("Claude API rate limited") from e
        except anthropic.APIStatusError as e:
            _log_call(**base, status="error", error=f"{e.status_code}: {e.message}", latency_ms=_ms(started))
            err = AIUnavailable(f"Claude API error {e.status_code}: {e.message}")
            err.retryable = e.status_code >= 500 or e.status_code in (408, 409, 429)
            raise err from e
        except anthropic.APIConnectionError as e:
            _log_call(**base, status="error", error=f"connection: {e}", latency_ms=_ms(started))
            raise AIUnavailable("Could not reach the Claude API") from e

        usage = self._usage_fields(message.model, message.usage)
        request_id = getattr(message, "_request_id", None)
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            _log_call(**base, **usage, status="refusal", error=str(details), latency_ms=_ms(started), request_id=request_id)
            raise AIRefusal(f"Model declined the request ({getattr(details, 'category', None)})")
        if message.stop_reason == "max_tokens":
            _log_call(**base, **usage, status="invalid", error="max_tokens", latency_ms=_ms(started), request_id=request_id)
            raise AIInvalidOutput("Model output was truncated (max_tokens)")

        text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        try:
            value = schema.model_validate_json(text)
        except ValidationError as e:
            _log_call(**base, **usage, status="invalid", error=str(e)[:4000], latency_ms=_ms(started), request_id=request_id)
            raise AIInvalidOutput(f"Output failed schema validation: {e.error_count()} errors") from e
        call_id = _log_call(**base, **usage, status="ok", latency_ms=_ms(started), request_id=request_id)
        return AIResult(value=value, call_id=call_id, model=message.model)

    def stream_text(self, *, role, system, messages, user_id=None, context=None):
        _check_budget()
        phash = _prompt_hash(system, messages)
        cfg, stream_mgr = self._request(role, system, messages, None)
        started = time.monotonic()
        base = dict(role=role, model=cfg.model, user_id=user_id, prompt_hash=phash, context=context or {})
        try:
            with stream_mgr as stream:
                for event in stream:
                    if getattr(event, "type", None) == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                        yield event.delta.text
                message = stream.get_final_message()
        except self._anthropic.APIError as e:
            _log_call(**base, status="error", error=str(e)[:2000], latency_ms=_ms(started))
            raise AIUnavailable("The tutor is temporarily unavailable.") from e
        usage = self._usage_fields(message.model, message.usage)
        status = "refusal" if message.stop_reason == "refusal" else "ok"
        _log_call(**base, **usage, status=status, latency_ms=_ms(started), request_id=getattr(message, "_request_id", None))
        if status == "refusal":
            yield "\n\n_(The model declined to continue this response.)_"


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# --------------------------------------------------------------------------- Fake

Handler = Callable[[str, str, dict], BaseModel | dict]


class FakeProvider:
    """Deterministic offline provider. Handlers are keyed by schema class name."""

    name = "fake"

    def __init__(self) -> None:
        from app.ai import fake_handlers

        self.handlers: dict[str, Handler] = dict(fake_handlers.DEFAULT_HANDLERS)
        self.calls: list[dict] = []

    def structured(self, *, role, system, prompt, schema, user_id=None, context=None):
        context = context or {}
        handler = self.handlers.get(schema.__name__)
        if handler is None:
            raise AIUnavailable(f"FakeProvider has no handler for {schema.__name__}")
        out = handler(system, prompt, context)
        value = out if isinstance(out, schema) else schema.model_validate(out)
        call_id = _log_call(
            role=role, model="fake", user_id=user_id, prompt_hash=_prompt_hash(system, prompt),
            status="ok", context=context | {"fake": True},
        )
        self.calls.append({"role": role, "schema": schema.__name__, "context": context})
        return AIResult(value=value, call_id=call_id, model="fake")

    def stream_text(self, *, role, system, messages, user_id=None, context=None):
        last = messages[-1]["content"] if messages else ""
        mode = (context or {}).get("mode", "explanation")
        reply = (
            f"[offline tutor · {mode} mode] Set AI_PROVIDER=anthropic and an API key for real tutoring.\n\n"
            f"You asked: _{str(last)[:200]}_. Try restating the idea in your own words, then check it "
            "against the lesson's key equations."
        )
        _log_call(role=role, model="fake", user_id=user_id, prompt_hash=_prompt_hash(system, messages), status="ok")
        for word in reply.split(" "):
            yield word + " "


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = FakeProvider() if get_settings().ai_provider == "fake" else AnthropicProvider()
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    """Test hook."""
    global _provider
    _provider = provider
