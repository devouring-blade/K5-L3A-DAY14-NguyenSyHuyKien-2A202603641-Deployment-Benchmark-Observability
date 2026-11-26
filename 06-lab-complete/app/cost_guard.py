"""Shared daily/monthly spending, stored as integer nano-USD."""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = Decimal("0.00015")
PRICE_OUTPUT_PER_1K = Decimal("0.0006")
UNITS = 1_000_000_000

def budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (f"{settings.environment}:cost:day:{now:%Y-%m-%d}",
            f"{settings.environment}:cost:month:{now:%Y-%m}")

def check_budget() -> None:
    daily, monthly = (int(value or 0) for value in r.mget(budget_keys()))
    if daily >= settings.daily_budget_usd * UNITS or monthly >= settings.monthly_budget_usd * UNITS:
        raise HTTPException(status_code=402, detail="LLM spending budget exhausted")

def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * PRICE_INPUT_PER_1K + output_tokens * PRICE_OUTPUT_PER_1K) / 1000
    amount = int(cost * UNITS)
    daily, monthly = budget_keys()
    with r.pipeline(transaction=True) as pipe:
        pipe.incrby(daily, amount)
        pipe.expire(daily, 172800)
        pipe.incrby(monthly, amount)
        pipe.expire(monthly, 5356800)
        pipe.execute()
    return float(cost)
