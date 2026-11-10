"""Price table (USD per million tokens, Anthropic first-party API) and budget checks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = PRICES.get(model, (10.0, 50.0))  # unknown model: assume the most expensive tier
    return (
        input_tokens * price_in
        + cache_read * price_in * CACHE_READ_MULTIPLIER
        + cache_write * price_in * CACHE_WRITE_MULTIPLIER
        + output_tokens * price_out
    ) / 1_000_000


def month_to_date_spend(db: Session) -> float:
    from app.models import AICall

    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(select(func.coalesce(func.sum(AICall.cost_usd), 0.0)).where(AICall.created_at >= start))
    return float(total or 0.0)
