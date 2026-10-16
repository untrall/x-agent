"""HTTP boundary for the local synthetic negotiation workbench."""

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from starlette.exceptions import HTTPException as StarletteHTTPException

from .demo import DEMO
from .store import DomainError, SessionStore


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartRequest(StrictModel):
    scenario_id: Literal["cofounder.v1"]
    candidate_agent_id: Literal["agent-b", "agent-c"]
    message_id: StrictStr = Field(min_length=1)


class AnswerRequest(StrictModel):
    question_id: StrictStr = Field(min_length=1)
    answer: Literal["accept_90_days", "require_ai_experience", "decline"]
    expected_revision: StrictInt
    message_id: StrictStr = Field(min_length=1)
    scope: Literal["session"]


class ApprovalRequest(StrictModel):
    proposal_digest: StrictStr = Field(min_length=1)
    approve: StrictBool
    expected_revision: StrictInt
    message_id: StrictStr = Field(min_length=1)


def _identity(authorization: str | None = Header(default=None)) -> str:
    identities = {
        "Bearer demo-owner-a": "owner-a",
        "Bearer demo-owner-b": "owner-b",
    }
    owner_id = identities.get(authorization)
    if owner_id is None:
        raise DomainError(401, "UNAUTHORIZED", "需要有效的合成演示身份令牌。")
    return owner_id


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = database_path or os.getenv("XAGENT_DB_PATH", ".local/xagent.sqlite3")
    store = SessionStore(path)
    app = FastAPI(title="X-Agent deterministic demo")

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": "请求字段无效。"}})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "接口不存在。" if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": message}})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "deterministic"}

    @app.get("/api/demo")
    def demo():
        return DEMO

    @app.post("/api/sessions", status_code=201)
    def start(request: StartRequest, owner_id: str = Depends(_identity)):
        return store.start(owner_id, request.model_dump())

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, owner_id: str = Depends(_identity)):
        return store.get(session_id, owner_id)

    @app.post("/api/sessions/{session_id}/answers")
    def answer(session_id: str, request: AnswerRequest, owner_id: str = Depends(_identity)):
        return store.answer(session_id, owner_id, request.model_dump())

    @app.post("/api/sessions/{session_id}/approvals")
    def approve(session_id: str, request: ApprovalRequest, owner_id: str = Depends(_identity)):
        return store.approve(session_id, owner_id, request.model_dump())

    @app.get("/api/sessions/{session_id}/artifact")
    def artifact(session_id: str, owner_id: str = Depends(_identity)):
        return store.artifact(session_id, owner_id)

    return app
