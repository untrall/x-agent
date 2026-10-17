"""Per-agent durable negotiation runtime."""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from contextlib import AsyncExitStack
from datetime import datetime, timezone

import httpx

from .chat import REPLY_MAX_CHARS, ChatError
from .models import CHAT_MAX_CHARS, TERMINAL_STATES, new_id, proposal_digest, validate_envelope
from .scenario import coerce_fact, evaluate_requirements, validate_requirement, validate_scenario
from .storage import Storage
from .profile import profile_view
from .policy import validate_answer


# True while an answer is given on the owner's behalf (the demo driver), so the
# ANSWER event can say so instead of looking like the owner typed it.
_PROXY_ANSWER: ContextVar[bool] = ContextVar("proxy_answer", default=False)


def _proxy_mark() -> dict:
    return {"proxy": True} if _PROXY_ANSWER.get() else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRuntime:
    def __init__(self, config: dict, policy=None, chat_model=None):
        self.config = dict(config)
        self.config["scenario"] = validate_scenario(self.config["scenario"])
        if not self.config.get("owner_token") or self.config["owner_token"] == self.config.get("token"):
            raise ValueError("owner_token must be set and distinct from peer token")
        self.agent_id = self.config["agent_id"]
        self.peers = {peer["agent_id"]: peer for peer in self.config.get("peers", [])}
        if self.config["owner_token"] in {peer["token"] for peer in self.peers.values()}:
            raise ValueError("owner_token must not be a peer token")
        self.profile = self.config["profile"]
        self.storage = Storage(self.config["database"])
        if policy is None:
            from .policy import DeterministicPolicy
            policy = DeterministicPolicy()
        self.policy = policy
        self.mode = policy.mode
        # Separate from the decision policy: only answers chat at the choice stage.
        self.chat_model = chat_model
        self._tasks: list[asyncio.Task] = []
        self._processing_tasks: set[asyncio.Task] = set()
        self._inflight_sessions: set[str] = set()
        self._running = False
        self._session_locks: dict[str, asyncio.Lock] = {}

    def snapshot(self) -> dict:
        return {
            "agent": {"agent_id": self.agent_id, "name": self.config["name"], "port": self.config["port"], "profile": self.profile},
            "mode": self.mode,
            "brain": {"model": getattr(self.policy, "model", None),
                      "reasoning": getattr(self.policy, "reasoning", None),
                      "chat_model": getattr(self.chat_model, "model", None)},
            "requests": self.storage.all("request"),
            "sessions": self.storage.all("session"),
            "questions": self.storage.all("question"),
            "events": self.storage.events(),
            "memory": self.storage.get("memory", "facts") or {},
            "metrics": {"pending_inbox": len(self.storage.pending_inbox()), "blocked_inbox": len(self.storage.blocked_inbox()), "pending_outbox": len(self.storage.queued_outbox())},
            "blocked_messages": self.storage.blocked_inbox(),
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._tasks = [asyncio.create_task(self._inbox_loop()), asyncio.create_task(self._outbox_loop())]

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._processing_tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._processing_tasks:
            await asyncio.gather(*self._processing_tasks, return_exceptions=True)
        self._tasks.clear()

    async def broadcast(self, text: str, requirements: list | None = None) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("request text is required")
        if requirements is None:
            requirements = await self.policy.extract(text, self.config["scenario"])
        requirements = [validate_requirement(item, self.config["scenario"]) for item in requirements]
        request_id = new_id()
        request = {"request_id": request_id, "text": text, "requirements": requirements, "revision": 1, "followup_done": False}
        session_ids = []
        with self.storage.transaction() as db:
            self.storage.put("request", request_id, request, db)
            for peer in self.peers.values():
                session_id = new_id()
                session_ids.append(session_id)
                session = self._new_session(session_id, request_id, peer["agent_id"], "requester", requirements)
                self.storage.put("session", session_id, session, db)
                self.storage.enqueue(self._envelope(session, "REQUEST", {"scenario_id": self.config["scenario"]["id"], "text": text, "requirements": requirements}), db)
                self.storage.event(_now(), "REQUEST_SENT", session_id, peer["agent_id"], f"Request queued for {peer['name']}", {"requirements": requirements}, db)
        return {"request_id": request_id, "session_ids": session_ids, "snapshot": self.snapshot()}

    def _new_session(self, session_id: str, request_id: str, peer_id: str, role: str, requirements: list) -> dict:
        return {"session_id": session_id, "request_id": request_id, "peer_id": peer_id, "role": role, "state": "ACTIVE", "revision": 1,
                "requirements": requirements, "terms": {}, "proposal": None, "approvals": [], "artifact": None,
                "pending_question_id": None, "peer_facts": {}, "facts_override": {}, "peer_evaluation": None}

    def _envelope(self, session: dict, message_type: str, payload: dict, causation_id: str | None = None) -> dict:
        return {"schema_version": 1, "message_id": new_id(), "request_id": session["request_id"], "session_id": session["session_id"],
                "sender_agent_id": self.agent_id, "recipient_agent_id": session["peer_id"], "type": message_type,
                "causation_id": causation_id, "payload": payload}

    def receive(self, envelope: dict, sender_id: str) -> bool:
        validate_envelope(envelope)
        self._validate_payload(envelope)
        if sender_id not in self.peers or envelope["sender_agent_id"] != sender_id or envelope["recipient_agent_id"] != self.agent_id:
            raise PermissionError("message sender/recipient identity mismatch")
        if envelope["type"] != "REQUEST":
            session = self.storage.get("session", envelope["session_id"])
            if session is None or session["peer_id"] != sender_id or session["request_id"] != envelope["request_id"]:
                raise PermissionError("message does not belong to this pair session")
        else:
            existing = self.storage.get("session", envelope["session_id"])
            if existing is not None and (existing["peer_id"] != sender_id or existing["request_id"] != envelope["request_id"]):
                raise PermissionError("request session identity mismatch")
            pending = self.storage.session_binding(envelope["session_id"])
            if pending is not None and pending != (sender_id, envelope["request_id"]):
                raise PermissionError("request session identity mismatch")
        return self.storage.receive(envelope)

    def _validate_payload(self, envelope: dict):
        kind, payload = envelope["type"], envelope["payload"]
        if kind == "REQUEST":
            if payload.get("scenario_id") != self.config["scenario"]["id"] or not isinstance(payload.get("text"), str) or not isinstance(payload.get("requirements"), list):
                raise ValueError("invalid request payload")
            for item in payload["requirements"]:
                validate_requirement(item, self.config["scenario"])
        elif kind == "REQUIREMENTS":
            if type(payload.get("revision")) is not int or not isinstance(payload.get("requirements"), list):
                raise ValueError("invalid requirements payload")
            for item in payload["requirements"]:
                validate_requirement(item, self.config["scenario"])
        elif kind == "FILTER":
            if payload.get("status") not in {"PASS", "FAIL", "UNKNOWN"} or not isinstance(payload.get("facts"), dict) or not isinstance(payload.get("reasons"), list) or type(payload.get("requirements_revision")) is not int:
                raise ValueError("invalid filter payload")
            if any(key not in self.config["scenario"]["fields"] for key in payload["facts"]):
                raise ValueError("filter has unknown fact field")
        elif kind == "PROPOSAL":
            if not isinstance(payload.get("digest"), str) or type(payload.get("version")) is not int or not isinstance(payload.get("terms"), dict):
                raise ValueError("invalid proposal payload")
        elif kind == "ACCEPT":
            if not isinstance(payload.get("digest"), str) or type(payload.get("version")) is not int:
                raise ValueError("invalid acceptance payload")
        elif kind == "APPROVAL":
            if not isinstance(payload.get("digest"), str):
                raise ValueError("invalid approval payload")
        elif kind == "REJECT":
            if not isinstance(payload.get("reason"), str):
                raise ValueError("invalid rejection payload")
        elif kind == "CHAT":
            text = payload.get("text")
            if not isinstance(payload.get("chat_id"), str) or not isinstance(text, str) or not text.strip() or len(text) > CHAT_MAX_CHARS:
                raise ValueError("invalid chat payload")
        elif kind == "CHAT_REPLY":
            text = payload.get("text")
            if not isinstance(payload.get("chat_id"), str) or not isinstance(text, str) or not text.strip() or len(text) > REPLY_MAX_CHARS or type(payload.get("ok")) is not bool:
                raise ValueError("invalid chat reply payload")

    async def _inbox_loop(self):
        while self._running:
            try:
                for envelope in self.storage.pending_inbox():
                    session_id = envelope["session_id"]
                    if session_id in self._inflight_sessions:
                        continue
                    self._inflight_sessions.add(session_id)
                    task = asyncio.create_task(self._process_one(envelope))
                    self._processing_tasks.add(task)
                    task.add_done_callback(self._processing_tasks.discard)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise

    async def _process_one(self, envelope: dict):
        try:
            lock = self._session_locks.setdefault(envelope["session_id"], asyncio.Lock())
            async with lock:
                await self._process(envelope)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with self.storage.transaction() as db:
                self.storage.block(envelope["message_id"], db)
                self.storage.event(_now(), "PROCESSING_ERROR", envelope["session_id"], envelope["sender_agent_id"], str(exc), {"message_id": envelope["message_id"], "blocked": True}, db)
        finally:
            self._inflight_sessions.discard(envelope["session_id"])

    def retry_blocked_message(self, message_id: str) -> dict:
        if not self.storage.retry_blocked(message_id):
            raise ValueError("blocked message not found")
        self.storage.event(_now(), "RETRY_REQUESTED", None, None, "Owner requested message retry", {"message_id": message_id})
        return self.snapshot()

    async def _outbox_loop(self):
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            while self._running:
                try:
                    for item in self.storage.pending_outbox():
                        if item["next_attempt"] > time.time():
                            continue
                        peer = self.peers.get(item["recipient"])
                        if peer is None:
                            continue
                        try:
                            response = await client.post(peer["url"].rstrip("/") + "/messages", json=item["envelope"], headers={"Authorization": f"Bearer {self.config['token']}"})
                            response.raise_for_status()
                            self.storage.delivered(item["message_id"])
                        except (httpx.HTTPError, ValueError):
                            self.storage.retry(item["message_id"], time.time() + min(5.0, 0.2 * 2 ** min(item["attempts"], 5)))
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise

    async def _process(self, envelope: dict):
        kind = envelope["type"]
        session = self.storage.get("session", envelope["session_id"])
        if kind == "REQUEST":
            await self._handle_request(envelope, session)
            return
        if session is None:
            raise ValueError("unknown pair session")
        if session["state"] in TERMINAL_STATES:
            with self.storage.transaction() as db:
                self.storage.mark_processed(envelope["message_id"], db)
            return
        if kind == "REQUIREMENTS":
            await self._handle_requirements(envelope, session)
        elif kind == "FILTER":
            await self._handle_filter(envelope, session)
        elif kind == "PROPOSAL":
            await self._handle_proposal(envelope, session)
        elif kind == "ACCEPT":
            self._handle_accept(envelope, session)
        elif kind == "APPROVAL":
            self._handle_approval(envelope, session)
        elif kind == "CHAT":
            await self._handle_chat(envelope, session)
        elif kind == "CHAT_REPLY":
            self._handle_chat_reply(envelope, session)
        elif kind == "REJECT":
            session["state"] = "NO_MATCH"
            session["revision"] += 1
            with self.storage.transaction() as db:
                self.storage.put("session", session["session_id"], session, db)
                self.storage.event(_now(), "REJECTED", session["session_id"], session["peer_id"], "Peer rejected this pair", envelope["payload"], db)
                self.storage.mark_processed(envelope["message_id"], db)
        else:
            raise ValueError(f"unsupported message {kind}")

    def _own_facts(self, session: dict) -> dict:
        return {**self.profile.get("facts", {}), **(self.storage.get("memory", "facts") or {}), **session.get("facts_override", {})}

    def _public_facts(self, facts: dict) -> dict:
        return {key: facts[key] for key in self.profile.get("public_fields", []) if key in facts and key in self.config["scenario"]["fields"]}

    async def _decide(self, session: dict, stage: str, evaluation: dict, question=None, owner_answer=None) -> dict:
        status = evaluation["status"]
        if stage == "followup":
            allowed_actions = {"ASK_OWNER"}
        elif stage == "proposal":
            allowed_actions = {"ACCEPT", "REJECT"} if status == "PASS" else {"REJECT"}
        elif session["role"] == "provider" and status == "UNKNOWN":
            allowed_actions = {"ASK_OWNER", "REJECT"}
        elif status == "PASS":
            allowed_actions = {"PROPOSE", "REJECT"}
        else:
            allowed_actions = {"REJECT"}
        context = {"scenario": self.config["scenario"], "role": session["role"], "stage": stage,
                   "peer_id": session["peer_id"], "session_id": session["session_id"], "request_id": session["request_id"],
                   "requirements": session["requirements"], "own_facts": self._own_facts(session),
                   "own_profile": profile_view(self.profile, self.config["scenario"], self._own_facts(session)),
                   "peer_facts": session.get("peer_facts", {}), "evaluation": evaluation,
                   "public_fields": list(self.profile.get("public_fields", [])),
                   "allowed_actions": sorted(allowed_actions),
                   "question": question, "owner_answer": owner_answer, "history": [],
                   "memory": self.storage.get("memory", "facts") or {}}
        decision = await self.policy.decide(context)
        required = {"action", "summary", "field", "question", "facts", "terms"}
        if not isinstance(decision, dict) or set(decision) != required:
            raise ValueError("policy decision schema invalid")
        if decision["action"] not in {"ASK_OWNER", "ASK_PEER", "PROPOSE", "ACCEPT", "REJECT", "WAIT"}:
            raise ValueError("policy action invalid")
        if decision["action"] not in allowed_actions:
            raise ValueError(f"policy action {decision['action']} is unsupported for {stage}/{session['role']}/{status}")
        if not isinstance(decision["facts"], dict) or not isinstance(decision["terms"], dict):
            raise ValueError("policy facts/terms invalid")
        allowed = self._public_facts(self._own_facts(session))
        if any(key not in allowed or allowed[key] != value for key, value in decision["facts"].items()):
            raise ValueError("policy invented or disclosed unauthorized facts")
        if evaluation["status"] == "FAIL" and decision["action"] in {"PROPOSE", "ACCEPT"}:
            raise ValueError("policy cannot override failing hard constraint")
        if evaluation["status"] == "UNKNOWN" and decision["action"] in {"PROPOSE", "ACCEPT"}:
            raise ValueError("policy cannot treat unknown as passed")
        self.storage.event(_now(), "POLICY_DECISION", session["session_id"], session["peer_id"], decision["summary"],
                           {"action": decision["action"], "field": decision["field"], "stage": stage, "role": session["role"],
                            "model": getattr(self.policy, "last_metadata", None) if self.mode != "deterministic" else None})
        return decision

    def _question(self, session: dict, field: str, scope: str, kind: str, title: str, reason: str) -> dict:
        question = {"question_id": new_id(), "session_id": session["session_id"] if scope == "session" else None,
                    "request_id": session["request_id"], "field": field, "title": title, "reason": reason,
                    "kind": kind, "revision": 1, "scope": scope, "options": ["是", "否"] if self.config["scenario"]["fields"][field]["type"] == "boolean" else None,
                    "answered": False}
        return question

    async def _provider_filter(self, session: dict, stage: str, causation_id: str | None, request=None, owner_answer=None, answered_question=None, memory=None):
        evaluation = evaluate_requirements(session["requirements"], self._own_facts(session), self.config["scenario"])
        decision = None
        if evaluation["status"] == "UNKNOWN" or (evaluation["status"] == "PASS" and (stage != "evaluate" or session.get("requirements_revision", 1) > 1)):
            decision = await self._decide(session, stage, evaluation, owner_answer=owner_answer)
            allowed_actions = {"ASK_OWNER", "REJECT"} if evaluation["status"] == "UNKNOWN" else {"PROPOSE", "REJECT"}
            if decision["action"] not in allowed_actions:
                raise ValueError(f"policy action {decision['action']} cannot handle provider {evaluation['status']}")
            if evaluation["status"] == "UNKNOWN" and decision["action"] == "ASK_OWNER" and decision["field"] not in evaluation["unknown_fields"]:
                raise ValueError("policy asked about an unrelated field")
        question = None
        old_question = self.storage.get("question", session["pending_question_id"]) if session.get("pending_question_id") else None
        superseded_question = None
        created_question = False
        if decision and decision["action"] == "REJECT":
            session["state"] = "NO_MATCH"
            session["pending_question_id"] = None
        elif evaluation["status"] == "UNKNOWN":
            field = decision["field"]
            if old_question and not old_question["answered"] and old_question["field"] == field:
                question = old_question
            else:
                question = self._question(session, field, "session", "fact", self.config["scenario"]["fields"][field]["label"], decision["question"] or f"Need your answer for {field}")
                created_question = True
            session["pending_question_id"] = question["question_id"]
            session["state"] = "WAITING_INPUT"
        elif evaluation["status"] == "FAIL":
            session["state"] = "NO_MATCH"
            session["pending_question_id"] = None
        else:
            session["state"] = "ACTIVE"
            session["pending_question_id"] = None
        if old_question and old_question is not question and not old_question["answered"]:
            old_question["answered"] = True
            old_question["superseded"] = True
            old_question["revision"] += 1
            superseded_question = old_question
        session["revision"] += 1
        policy_reject = bool(decision and decision["action"] == "REJECT")
        payload = {"status": evaluation["status"], "reasons": evaluation["reasons"], "unknown_fields": evaluation["unknown_fields"],
                   "facts": self._public_facts(self._own_facts(session)), "requirements_revision": session.get("requirements_revision", 1)}
        with self.storage.transaction() as db:
            if request is not None:
                self.storage.put("request", session["request_id"], request, db)
                if stage == "evaluate" and causation_id is not None and request["revision"] == 1:
                    self.storage.event(_now(), "REQUEST_RECEIVED", session["session_id"], session["peer_id"], "Peer request received", {"requirements": session["requirements"]}, db)
            if answered_question is not None:
                self.storage.put("question", answered_question["question_id"], answered_question, db)
                self.storage.event(_now(), "ANSWER", session["session_id"], session["peer_id"], "Owner answered fact question", {"question_id": answered_question["question_id"], "field": answered_question["field"], **_proxy_mark()}, db)
            if memory is not None:
                # Merge only this answer's field against the latest memory inside
                # the transaction; other pair sessions can answer concurrently.
                latest_memory = self.storage.get('memory', 'facts') or {}
                latest_memory.update(memory)
                self.storage.put("memory", "facts", latest_memory, db)
            self.storage.put("session", session["session_id"], session, db)
            if superseded_question:
                self.storage.put("question", superseded_question["question_id"], superseded_question, db)
            if created_question:
                self.storage.put("question", question["question_id"], question, db)
                self.storage.event(_now(), "QUESTION", session["session_id"], session["peer_id"], question["title"], {"question_id": question["question_id"]}, db)
            if policy_reject:
                self.storage.enqueue(self._envelope(session, "REJECT", {"reason": "Provider declined this pair"}, causation_id), db)
                self.storage.event(_now(), "REJECTED", session["session_id"], session["peer_id"], decision["summary"], {"action": "REJECT"}, db)
            else:
                self.storage.enqueue(self._envelope(session, "FILTER", payload, causation_id), db)
                self.storage.event(_now(), "FILTERED" if evaluation["status"] == "FAIL" else "FILTER_RESULT", session["session_id"], session["peer_id"], f"Local filter {evaluation['status']}", {"status": evaluation["status"], "reasons": evaluation["reasons"]}, db)
            if causation_id is not None:
                self.storage.mark_processed(causation_id, db)

    async def _handle_request(self, envelope: dict, existing: dict | None):
        payload = envelope["payload"]
        if payload.get("scenario_id") != self.config["scenario"]["id"]:
            raise ValueError("scenario mismatch")
        requirements = [validate_requirement(item, self.config["scenario"]) for item in payload.get("requirements", [])]
        if existing is not None:
            with self.storage.transaction() as db:
                self.storage.mark_processed(envelope["message_id"], db)
            return
        session = self._new_session(envelope["session_id"], envelope["request_id"], envelope["sender_agent_id"], "provider", requirements)
        session["requirements_revision"] = 1
        request = {"request_id": envelope["request_id"], "text": payload.get("text", ""), "requirements": requirements, "revision": 1, "followup_done": False}
        await self._provider_filter(session, "evaluate", envelope["message_id"], request=request)

    async def _handle_requirements(self, envelope: dict, session: dict):
        if session["role"] != "provider":
            raise PermissionError("requirements are requester-owned")
        payload = envelope["payload"]
        revision = payload.get("revision")
        if type(revision) is not int or revision <= session.get("requirements_revision", 1):
            with self.storage.transaction() as db:
                self.storage.mark_processed(envelope["message_id"], db)
            return
        session["requirements"] = [validate_requirement(item, self.config["scenario"]) for item in payload["requirements"]]
        session["requirements_revision"] = revision
        session["proposal"] = None
        session["approvals"] = []
        session["artifact"] = None
        request = self.storage.get("request", session["request_id"])
        request["requirements"] = session["requirements"]
        request["revision"] = revision
        await self._provider_filter(session, "evaluate", envelope["message_id"], request=request)

    async def _handle_filter(self, envelope: dict, session: dict):
        if session["role"] != "requester":
            raise PermissionError("only provider may filter")
        payload = envelope["payload"]
        if payload.get("status") not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("invalid filter status")
        request = self.storage.get("request", session["request_id"])
        session["peer_facts"] = payload.get("facts", {})
        session["peer_evaluation"] = {"status": payload["status"], "reasons": payload.get("reasons", []), "unknown_fields": payload.get("unknown_fields", [])}
        session["revision"] += 1
        if payload["status"] == "FAIL":
            session["state"] = "NO_MATCH"
            with self.storage.transaction() as db:
                self.storage.put("session", session["session_id"], session, db)
                self.storage.event(_now(), "NO_MATCH", session["session_id"], session["peer_id"], "Peer does not meet requirements", {"reasons": payload.get("reasons", [])}, db)
                self.storage.mark_processed(envelope["message_id"], db)
            return
        followup = self.config["scenario"].get("followup")
        needs_followup = followup and not request["followup_done"] and not any(row["field"] == followup["field"] for row in request["requirements"])
        if needs_followup:
            decision = await self._decide(session, "followup", session["peer_evaluation"])
            if decision["action"] != "ASK_OWNER" or decision["field"] != followup["field"]:
                raise ValueError("policy did not request the configured followup")
            request = self.storage.get("request", session["request_id"])
            if not request["followup_done"]:
                existing = next((q for q in self.storage.all("question") if q["request_id"] == request["request_id"] and q["field"] == followup["field"] and q["scope"] == "request" and not q["answered"]), None)
                question = existing or self._question(session, followup["field"], "request", "additional_requirements", followup["title"], decision["question"] or followup["prompt"])
                session["state"] = "WAITING_INPUT"
                session["pending_question_id"] = question["question_id"]
                with self.storage.transaction() as db:
                    self.storage.put("session", session["session_id"], session, db)
                    if existing is None:
                        self.storage.put("question", question["question_id"], question, db)
                        self.storage.event(_now(), "QUESTION", None, None, question["title"], {"question_id": question["question_id"], "scope": "request"}, db)
                    self.storage.mark_processed(envelope["message_id"], db)
                return
        if not request["followup_done"]:
            request["followup_done"] = True
        if payload.get("requirements_revision", 1) < request["revision"]:
            session["state"] = "ACTIVE"
            session["requirements"] = request["requirements"]
            with self.storage.transaction() as db:
                self.storage.put("request", request["request_id"], request, db)
                self.storage.put("session", session["session_id"], session, db)
                self.storage.enqueue(self._envelope(session, "REQUIREMENTS", {"requirements": request["requirements"], "revision": request["revision"]}, envelope["message_id"]), db)
                self.storage.mark_processed(envelope["message_id"], db)
            return
        if payload["status"] == "UNKNOWN":
            session["state"] = "ACTIVE"
            with self.storage.transaction() as db:
                self.storage.put("session", session["session_id"], session, db)
                self.storage.mark_processed(envelope["message_id"], db)
            return
        decision = await self._decide(session, "evaluate", session["peer_evaluation"])
        if decision["action"] == "REJECT":
            session["state"] = "NO_MATCH"
            with self.storage.transaction() as db:
                self.storage.put("session", session["session_id"], session, db)
                self.storage.enqueue(self._envelope(session, "REJECT", {"reason": "Requester declined this pair"}, envelope["message_id"]), db)
                self.storage.event(_now(), "REJECTED", session["session_id"], session["peer_id"], decision["summary"], {"action": "REJECT"}, db)
                self.storage.mark_processed(envelope["message_id"], db)
            return
        if decision["action"] != "PROPOSE":
            raise ValueError("policy did not propose after passing filter")
        self._make_proposal(session, envelope["message_id"])
        with self.storage.transaction() as db:
            self.storage.put("request", request["request_id"], request, db)
            self.storage.put("session", session["session_id"], session, db)
            self.storage.enqueue(self._envelope(session, "PROPOSAL", session["proposal"], envelope["message_id"]), db)
            self.storage.event(_now(), "PROPOSAL", session["session_id"], session["peer_id"], "Proposal sent", {"digest": session["proposal"]["digest"]}, db)
            self.storage.mark_processed(envelope["message_id"], db)

    def _make_proposal(self, session: dict, causation_id: str):
        terms = {"requirements": session["requirements"], "provider_facts": session["peer_facts"]}
        version = (session.get("proposal") or {}).get("version", 0) + 1
        digest = proposal_digest(self.config["scenario"]["id"], self.agent_id, session["peer_id"], terms, version)
        session["terms"] = terms
        session["proposal"] = {"digest": digest, "version": version, "terms": terms}
        session["approvals"] = []
        session["artifact"] = None
        session["state"] = "PROPOSED"
        session["revision"] += 1

    async def _handle_proposal(self, envelope: dict, session: dict):
        if session["role"] != "provider":
            raise PermissionError("only requester may propose")
        proposal = envelope["payload"]
        terms = proposal.get("terms")
        version = proposal.get("version")
        if not isinstance(terms, dict) or type(version) is not int or version < 1 or terms.get("requirements") != session["requirements"]:
            raise ValueError("proposal terms do not match current requirements")
        if terms.get("provider_facts") != self._public_facts(self._own_facts(session)):
            raise ValueError("proposal provider facts differ from current disclosed facts")
        digest = proposal_digest(self.config["scenario"]["id"], session["peer_id"], self.agent_id, terms, version)
        if proposal.get("digest") != digest:
            raise ValueError("proposal digest mismatch")
        evaluation = evaluate_requirements(session["requirements"], self._own_facts(session), self.config["scenario"])
        decision = await self._decide(session, "proposal", evaluation) if evaluation["status"] == "PASS" else {"action": "REJECT", "summary": "Required facts no longer establish a match"}
        if decision["action"] == "REJECT":
            session["state"] = "NO_MATCH"
            session["revision"] += 1
            with self.storage.transaction() as db:
                self.storage.put("session", session["session_id"], session, db)
                self.storage.enqueue(self._envelope(session, "REJECT", {"reason": "Provider declined proposal", "digest": digest}, envelope["message_id"]), db)
                self.storage.event(_now(), "REJECTED", session["session_id"], session["peer_id"], decision["summary"], {"digest": digest}, db)
                self.storage.mark_processed(envelope["message_id"], db)
            return
        if evaluation["status"] != "PASS" or decision["action"] != "ACCEPT":
            raise ValueError("proposal cannot be accepted against current facts")
        session["terms"] = terms
        session["proposal"] = {"digest": digest, "version": version, "terms": terms}
        session["state"] = "PENDING_APPROVAL"
        session["revision"] += 1
        with self.storage.transaction() as db:
            self.storage.put("session", session["session_id"], session, db)
            self.storage.enqueue(self._envelope(session, "ACCEPT", {"digest": digest, "version": version}, envelope["message_id"]), db)
            self.storage.event(_now(), "PENDING_APPROVAL", session["session_id"], session["peer_id"], "Proposal awaits owner approval", {"digest": digest}, db)
            self.storage.mark_processed(envelope["message_id"], db)

    def _handle_accept(self, envelope: dict, session: dict):
        proposal = session.get("proposal")
        if session["role"] != "requester" or proposal is None or session["state"] != "PROPOSED":
            raise ValueError("no live proposal to accept")
        if envelope["payload"].get("digest") != proposal["digest"] or envelope["payload"].get("version") != proposal["version"]:
            raise ValueError("stale proposal acceptance")
        session["state"] = "PENDING_APPROVAL"
        session["revision"] += 1
        with self.storage.transaction() as db:
            self.storage.put("session", session["session_id"], session, db)
            self.storage.event(_now(), "PENDING_APPROVAL", session["session_id"], session["peer_id"], "Proposal awaits owner approval", {"digest": proposal["digest"]}, db)
            self.storage.mark_processed(envelope["message_id"], db)

    def _artifact(self, session: dict) -> dict:
        proposal = session["proposal"]
        requester = self.agent_id if session["role"] == "requester" else session["peer_id"]
        provider = session["peer_id"] if session["role"] == "requester" else self.agent_id
        return {"title": self.config["scenario"]["result_title"], "session_id": session["session_id"], "request_id": session["request_id"],
                "scenario_id": self.config["scenario"]["id"], "requester_id": requester, "provider_id": provider,
                "proposal_digest": proposal["digest"], "terms": proposal["terms"], "approvals": sorted(session["approvals"]),
                "next_step": "双方自行安排进一步沟通"}

    def _handle_approval(self, envelope: dict, session: dict):
        proposal = session.get("proposal")
        if session["state"] != "PENDING_APPROVAL" or proposal is None or envelope["payload"].get("digest") != proposal["digest"]:
            raise ValueError("stale or unexpected peer approval")
        if envelope["sender_agent_id"] not in session["approvals"]:
            session["approvals"].append(envelope["sender_agent_id"])
        if {self.agent_id, session["peer_id"]} <= set(session["approvals"]):
            session["state"] = "CONNECTED"
            session["artifact"] = self._artifact(session)
        session["revision"] += 1
        with self.storage.transaction() as db:
            self.storage.put("session", session["session_id"], session, db)
            self.storage.event(_now(), "CONNECTED" if session["artifact"] else "APPROVAL", session["session_id"], session["peer_id"], "Both owners approved" if session["artifact"] else "Peer approved", {"digest": proposal["digest"]}, db)
            if session["artifact"]:
                self._decline_rivals(session, db)
            self.storage.mark_processed(envelope["message_id"], db)

    # ------------------------------------------------------------ choice-stage chat

    def _chat_history(self, session_id: str) -> list[dict]:
        events = [e for e in self.storage.events() if e.get("session_id") == session_id]
        asked = {e["payload"].get("chat_id"): e["payload"].get("text") for e in events if e["type"] == "CHAT_RECEIVED"}
        return [{"question": asked[e["payload"]["chat_id"]], "reply": e["payload"]["text"]}
                for e in events if e["type"] == "CHAT_REPLIED" and e["payload"].get("ok") and e["payload"].get("chat_id") in asked]

    async def chat(self, session_id: str, text: str) -> dict:
        """Owner (requester) asks a candidate's agent a free-form question."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("聊天内容不能为空")
        text = text.strip()
        if len(text) > CHAT_MAX_CHARS:
            raise ValueError(f"聊天内容不能超过 {CHAT_MAX_CHARS} 字")
        async with self._session_locks.setdefault(session_id, asyncio.Lock()):
            session = self.storage.get("session", session_id)
            if session is None or session["role"] != "requester":
                raise ValueError("只能和自己发起需求的候选聊天")
            if session["state"] != "PENDING_APPROVAL" or self.agent_id in session["approvals"]:
                raise ValueError("只有在提案待你确认时才能聊天")
            chat_id = new_id()
            with self.storage.transaction() as db:
                self.storage.enqueue(self._envelope(session, "CHAT", {"chat_id": chat_id, "text": text}), db)
                self.storage.event(_now(), "CHAT_SENT", session_id, session["peer_id"], text, {"chat_id": chat_id, "text": text}, db)
        return self.snapshot()

    async def _handle_chat(self, envelope: dict, session: dict):
        if session["role"] != "provider":
            raise PermissionError("only the requester may start a chat")
        chat_id = envelope["payload"]["chat_id"]
        question = envelope["payload"]["text"].strip()
        name, peer = self.config["name"], self.peers[session["peer_id"]]["name"]
        history = self._chat_history(session["session_id"])
        # Record the question first so the owner window shows it while the model thinks.
        if not any(e["type"] == "CHAT_RECEIVED" and e["payload"].get("chat_id") == chat_id for e in self.storage.events()):
            self.storage.event(_now(), "CHAT_RECEIVED", session["session_id"], session["peer_id"], question, {"chat_id": chat_id, "text": question})
        persona = self.profile.get("persona") or {"description": self.profile.get("description", ""), "tags": self.profile.get("tags", [])}
        if self.chat_model is None:
            ok, reply = False, f"{name}的 Agent 没有连接聊天模型，暂时没法回答。"
        else:
            try:
                ok, reply = True, await self.chat_model.reply(name=name, peer=peer, persona=persona, history=history, question=question)
            except ChatError as exc:
                ok, reply = False, f"{name}的 Agent 暂时没法回答（{exc}），可以稍后再问一次。"
        payload = {"chat_id": chat_id, "text": reply, "ok": ok}
        with self.storage.transaction() as db:
            self.storage.enqueue(self._envelope(session, "CHAT_REPLY", payload, envelope["message_id"]), db)
            self.storage.event(_now(), "CHAT_REPLIED", session["session_id"], session["peer_id"], reply, payload, db)
            self.storage.mark_processed(envelope["message_id"], db)

    def _handle_chat_reply(self, envelope: dict, session: dict):
        if session["role"] != "requester":
            raise PermissionError("chat replies only go to the requester")
        payload = envelope["payload"]
        with self.storage.transaction() as db:
            self.storage.event(_now(), "CHAT_REPLY", session["session_id"], session["peer_id"], payload["text"], payload, db)
            self.storage.mark_processed(envelope["message_id"], db)

    async def choose(self, session_id: str) -> dict:
        """Owner picks one pending proposal and asks that candidate to accept.

        Two-way consent: the others stay pending until the chosen candidate
        accepts (then _decline_rivals declines them) or declines (then the
        owner may choose again among the rest).
        """
        chosen = self.storage.get("session", session_id)
        if chosen is None or chosen["role"] != "requester":
            raise ValueError("只能选择自己发起需求的候选")
        ids = sorted(s["session_id"] for s in self.storage.all("session")
                     if s["role"] == "requester" and s["request_id"] == chosen["request_id"])
        async with AsyncExitStack() as stack:
            for sid in ids:
                await stack.enter_async_context(self._session_locks.setdefault(sid, asyncio.Lock()))
            sessions = [self.storage.get("session", sid) for sid in ids]
            waiting = next((s for s in sessions if s["state"] == "PENDING_APPROVAL" and self.agent_id in s["approvals"]), None)
            if waiting is not None:
                raise ValueError(f"正在等待 {self.peers[waiting['peer_id']]['name']} 回应，暂时不能改选")
            current = next(s for s in sessions if s["session_id"] == session_id)
            if current["state"] != "PENDING_APPROVAL" or self.agent_id in current["approvals"]:
                raise ValueError("这位候选的提案不在待确认状态")
            return self._approve_unlocked(session_id, True, current["proposal"]["digest"])

    def _decline_rivals(self, connected: dict, db) -> None:
        """Once a requester pair connects, decline the other still-pending pairs."""
        if connected["role"] != "requester":
            return
        for session in self.storage.all("session"):
            if (session["role"] != "requester" or session["request_id"] != connected["request_id"]
                    or session["session_id"] == connected["session_id"] or session["state"] != "PENDING_APPROVAL"):
                continue
            digest = (session.get("proposal") or {}).get("digest")
            session["state"] = "REJECTED"
            session["revision"] += 1
            self.storage.put("session", session["session_id"], session, db)
            self.storage.enqueue(self._envelope(session, "REJECT", {"reason": "owner rejected proposal", "digest": digest}), db)
            self.storage.event(_now(), "REJECTED", session["session_id"], session["peer_id"], "Owner rejected proposal", {"digest": digest}, db)

    async def answer(self, question_id: str, text: str, remember: bool = False, expected_revision: int | None = None,
                     proxy: bool = False) -> dict:
        token = _PROXY_ANSWER.set(bool(proxy))
        try:
            return await self._answer_locked(question_id, text, remember, expected_revision)
        finally:
            _PROXY_ANSWER.reset(token)

    async def _answer_locked(self, question_id: str, text: str, remember: bool, expected_revision: int | None) -> dict:
        question = self.storage.get("question", question_id)
        if question is None:
            raise ValueError("question is missing or already answered")
        if question["scope"] == "session":
            ids = [question["session_id"]]
        else:
            ids = sorted(session["session_id"] for session in self.storage.all("session") if session["request_id"] == question["request_id"] and session["role"] == "requester")
        async with AsyncExitStack() as stack:
            for session_id in ids:
                await stack.enter_async_context(self._session_locks.setdefault(session_id, asyncio.Lock()))
            return await self._answer_unlocked(question_id, text, remember, expected_revision)

    async def _answer_unlocked(self, question_id: str, text: str, remember: bool = False, expected_revision: int | None = None) -> dict:
        question = self.storage.get("question", question_id)
        if question is None or question["answered"]:
            raise ValueError("question is missing or already answered")
        if expected_revision is not None and expected_revision != question["revision"]:
            raise ValueError("stale question revision")
        field = question["field"]
        interpret = getattr(self.policy, 'interpret_answer', None)
        if interpret is None:
            try:
                value = coerce_fact(field, text, self.config['scenario'])
            except ValueError:
                raise ValueError('当前为确定性模式；自然语言理解需要以 --mode codex 启动。当前可输入明确的“是 / 否”或数字。') from None
        else:
            # In model mode even short answers need the current question context.
            result = validate_answer(await interpret(text, question, self.config['scenario']), field, self.config['scenario'])
            if result['status'] == 'clarify':
                raise ValueError('需要补充：' + result['clarification'])
            value = result['value']
        # Preserve both the owner's original wording and the typed interpretation.
        # Nothing is persisted until the normal answer transaction succeeds.
        question['interpreted_value'] = value
        if question["scope"] == "request":
            request = self.storage.get("request", question["request_id"])
            if question["kind"] != "additional_requirements" or type(value) is not bool:
                raise ValueError("unsupported request-wide answer")
            if value:
                requirement = {"field": field, "op": "eq", "value": True}
                if requirement not in request["requirements"]:
                    request["requirements"].append(requirement)
            request["revision"] += 1
            request["followup_done"] = True
            question["answered"] = True
            question["answer"] = text
            question["revision"] += 1
            with self.storage.transaction() as db:
                self.storage.put("request", request["request_id"], request, db)
                self.storage.put("question", question_id, question, db)
                for session in self.storage.all("session"):
                    if session["request_id"] != request["request_id"] or session["role"] != "requester" or session["state"] in TERMINAL_STATES:
                        continue
                    session["requirements"] = request["requirements"]
                    session["pending_question_id"] = None
                    session["state"] = "ACTIVE"
                    session["proposal"] = None
                    session["approvals"] = []
                    session["revision"] += 1
                    self.storage.put("session", session["session_id"], session, db)
                    self.storage.enqueue(self._envelope(session, "REQUIREMENTS", {"requirements": request["requirements"], "revision": request["revision"]}), db)
                self.storage.event(_now(), "ANSWER", None, None, "Owner answered request question", {"question_id": question_id, "field": field, **_proxy_mark()}, db)
            return self.snapshot()
        session = self.storage.get("session", question["session_id"])
        if session is None or session["state"] != "WAITING_INPUT" or session["pending_question_id"] != question_id:
            raise ValueError("question is not active in its pair session")
        session["facts_override"][field] = value
        session["pending_question_id"] = None
        question["answered"] = True
        question["answer"] = text
        question["revision"] += 1
        memory = None
        if remember:
            memory = {field: value}
        await self._provider_filter(session, "after_answer", None, owner_answer=text, answered_question=question, memory=memory)
        return self.snapshot()

    async def approve(self, session_id: str, approve: bool, proposal_digest: str | None = None, expected_revision: int | None = None) -> dict:
        async with self._session_locks.setdefault(session_id, asyncio.Lock()):
            return self._approve_unlocked(session_id, approve, proposal_digest, expected_revision)

    def _approve_unlocked(self, session_id: str, approve: bool, proposal_digest: str | None = None, expected_revision: int | None = None) -> dict:
        session = self.storage.get("session", session_id)
        if session is None or session["state"] != "PENDING_APPROVAL" or session["proposal"] is None:
            raise ValueError("session has no pending proposal")
        if expected_revision is not None and expected_revision != session["revision"]:
            raise ValueError("stale session revision")
        digest = session["proposal"]["digest"]
        if proposal_digest is not None and proposal_digest != digest:
            raise ValueError("proposal digest mismatch")
        if type(approve) is not bool:
            raise ValueError("approve must be boolean")
        if self.agent_id in session["approvals"]:
            raise ValueError("owner has already approved")
        with self.storage.transaction() as db:
            if not approve:
                session["state"] = "REJECTED"
                self.storage.enqueue(self._envelope(session, "REJECT", {"reason": "owner rejected proposal", "digest": digest}), db)
                event_type = "REJECTED"
                summary = "Owner rejected proposal"
            else:
                session["approvals"].append(self.agent_id)
                self.storage.enqueue(self._envelope(session, "APPROVAL", {"digest": digest}), db)
                if {self.agent_id, session["peer_id"]} <= set(session["approvals"]):
                    session["state"] = "CONNECTED"
                    session["artifact"] = self._artifact(session)
                event_type = "CONNECTED" if session["artifact"] else "APPROVAL"
                summary = "Both owners approved" if session["artifact"] else "Owner approved proposal"
            session["revision"] += 1
            self.storage.put("session", session_id, session, db)
            self.storage.event(_now(), event_type, session_id, session["peer_id"], summary, {"digest": digest}, db)
            if session["artifact"]:
                self._decline_rivals(session, db)
        return self.snapshot()
