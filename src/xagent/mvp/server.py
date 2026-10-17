"""Loopback owner and authenticated peer HTTP endpoints."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .runtime import AgentRuntime


def create_peer_app(runtime: AgentRuntime) -> FastAPI:
    app = FastAPI(title="X-Agent local peer")

    def bearer(request: Request) -> str:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="bearer token required")
        return header[7:]

    def owner(request: Request):
        if bearer(request) != runtime.config["owner_token"]:
            raise HTTPException(status_code=401, detail="owner token rejected")

    def fail(exc: Exception):
        if isinstance(exc, PermissionError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise exc

    @app.get("/health")
    async def health():
        return {"ok": True, "agent_id": runtime.agent_id}

    @app.get("/owner/state")
    async def state(request: Request):
        owner(request)
        return runtime.snapshot()

    @app.post("/owner/requests")
    async def requests(request: Request, body: dict):
        owner(request)
        try:
            return await runtime.broadcast(body.get("text", ""), body.get("requirements"))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/owner/answers")
    async def answers(request: Request, body: dict):
        owner(request)
        try:
            return await runtime.answer(body.get("question_id", ""), body.get("text", ""), body.get("remember", False), body.get("expected_revision"))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/owner/approvals")
    async def approvals(request: Request, body: dict):
        owner(request)
        try:
            return await runtime.approve(body.get("session_id", ""), body.get("approve"), body.get("proposal_digest"), body.get("expected_revision"))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/owner/chat")
    async def chat(request: Request, body: dict):
        owner(request)
        try:
            return await runtime.chat(body.get("session_id", ""), body.get("text", ""))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/owner/choose")
    async def choose(request: Request, body: dict):
        owner(request)
        try:
            return await runtime.choose(body.get("session_id", ""))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/owner/retry")
    async def retry(request: Request, body: dict):
        owner(request)
        try:
            return runtime.retry_blocked_message(body.get("message_id", ""))
        except (PermissionError, ValueError) as exc:
            fail(exc)

    @app.post("/messages")
    async def messages(request: Request, body: dict):
        sender_id = body.get("sender_agent_id")
        peer = runtime.peers.get(sender_id)
        if peer is None or bearer(request) != peer["token"]:
            raise HTTPException(status_code=401, detail="peer token rejected")
        try:
            accepted = runtime.receive(body, sender_id)
            return {"accepted": accepted, "message_id": body.get("message_id")}
        except (PermissionError, ValueError) as exc:
            fail(exc)

    return app
