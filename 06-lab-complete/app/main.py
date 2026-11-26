"""Production agent with auth, shared limits, probes and structured logs."""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from redis.exceptions import RedisError
from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname, "event": record.getMessage(),
            **getattr(record, "fields", {})}, ensure_ascii=False)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [handler]
logger.setLevel(settings.log_level)
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uvicorn handles SIGTERM, drains requests, then runs lifespan cleanup.
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    yield
    r.close()
    logger.info("shutdown")

app = FastAPI(title="Production AI Agent", lifespan=lifespan)

@app.middleware("http")
async def request_log(request: Request, call_next):
    started, request_id, status = time.perf_counter(), uuid.uuid4().hex, 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        logger.info("http_request", extra={"fields": {
            "request_id": request_id, "method": request.method,
            "path": route.path if route else "unmatched", "status": status,
            "ms": round((time.perf_counter() - started) * 1000, 2)}})

@app.exception_handler(RedisError)
async def redis_unavailable(request: Request, exc: RedisError):
    logger.warning("redis_unavailable")
    return JSONResponse(status_code=503, content={"detail": "State store unavailable; please retry"})

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("request_failed", extra={"fields": {"error_type": type(exc).__name__}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=200)

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain text")
        return value.strip()

@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}

@app.get("/ready")
def ready():
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "redis": "unavailable"})
    return {"ready": True}

@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    check_rate_limit(key)
    check_budget()
    answer = llm_ask(body.question)
    input_tokens, output_tokens = max(1, len(body.question) // 4), max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)
    return {"question": body.question, "answer": answer, "usage": {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}}
