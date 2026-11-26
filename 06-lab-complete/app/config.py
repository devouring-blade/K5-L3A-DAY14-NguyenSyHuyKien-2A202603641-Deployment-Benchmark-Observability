"""12-Factor configuration; secrets come from the environment."""
import os
from dataclasses import dataclass, field
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: Decimal = field(default_factory=lambda: Decimal(os.getenv("DAILY_BUDGET_USD", "1")))
    monthly_budget_usd: Decimal = field(default_factory=lambda: Decimal(os.getenv("MONTHLY_BUDGET_USD", "10")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    def __post_init__(self):
        if not 1 <= self.port <= 65535 or self.rate_limit_per_minute < 1:
            raise ValueError("Invalid PORT or RATE_LIMIT_PER_MINUTE")
        for budget in (self.daily_budget_usd, self.monthly_budget_usd):
            if not budget.is_finite() or budget < 0:
                raise ValueError("Budgets must be finite nonnegative USD amounts")

settings = Settings()
