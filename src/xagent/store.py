"""Atomic SQLite state transitions for the bounded deterministic demo."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event(session, actor, kind, summary, payload=None):
    session["events"].append({
        "seq": len(session["events"]) + 1,
        "session_id": session["session_id"],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": actor, "type": kind, "public_summary": summary,
        "payload": payload or {}, "mode": "deterministic",
    })


class SessionStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    owner_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response TEXT NOT NULL,
                    PRIMARY KEY(owner_id, message_id)
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def _existing(self, db, owner_id, message_id, route_key, request):
        row = db.execute("SELECT * FROM idempotency WHERE owner_id = ? AND message_id = ?",
                         (owner_id, message_id)).fetchone()
        if row is None:
            return None
        request_hash = hashlib.sha256(_canonical(request).encode()).hexdigest()
        if row["route_key"] != route_key or row["request_hash"] != request_hash:
            raise DomainError(409, "MESSAGE_ID_CONFLICT", "message_id 已用于其他请求。")
        return json.loads(row["response"])

    def _remember(self, db, owner_id, message_id, route_key, request, response):
        db.execute("INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)", (
            owner_id, message_id, route_key,
            hashlib.sha256(_canonical(request).encode()).hexdigest(), _canonical(response),
        ))

    def _load(self, db, session_id):
        row = db.execute("SELECT snapshot FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise DomainError(404, "SESSION_NOT_FOUND", "会话不存在。")
        return json.loads(row["snapshot"])

    def _save(self, db, session):
        db.execute("UPDATE sessions SET snapshot = ? WHERE session_id = ?",
                   (_canonical(session), session["session_id"]))

    def get(self, session_id, owner_id):
        with self._connection() as db:
            session = self._load(db, session_id)
            self._participant(session, owner_id)
            return session

    @staticmethod
    def _participant(session, owner_id):
        allowed = ("owner-a", "owner-b") if session["candidate_agent_id"] == "agent-b" else ("owner-a",)
        if owner_id not in allowed:
            raise DomainError(403, "FORBIDDEN", "无权查看此会话。")

    def start(self, owner_id, request):
        if owner_id != "owner-a":
            raise DomainError(403, "FORBIDDEN", "仅林澈可发起此合成场景。")
        route_key = "POST /api/sessions"
        with self._transaction() as db:
            existing = self._existing(db, owner_id, request["message_id"], route_key, request)
            if existing is not None:
                return existing
            session_id = str(uuid4())
            candidate = request["candidate_agent_id"]
            session = {
                "session_id": session_id, "scenario_id": "cofounder.v1",
                "candidate_agent_id": candidate, "mode": "deterministic",
                "state": "READY", "revision": 1,
                "profile_versions": {"owner-a": 1, "owner-b": 1},
                "rounds": 0, "terms": {
                    "start_in_days": 90, "hours_per_week": 15 if candidate == "agent-b" else 2,
                    "trial_days": 14 if candidate == "agent-b" else 0,
                    "requires_ai_experience": False,
                    "ai_product_experience": True if candidate == "agent-b" else False,
                },
                "proposal": None, "pending_question": None,
                "approvals": [], "events": [], "artifact": None,
            }
            _event(session, "system", "SESSION_CREATED", "已创建合成创业合伙人协商会话。")
            session["revision"] = 2
            session["rounds"] = 1
            if candidate == "agent-c":
                session["state"] = "NO_MATCH"
                _event(session, "agent-a", "HARD_CONSTRAINT_REJECTED",
                       "候选人每周只能投入 2 小时，未达到 15 小时硬性要求。",
                       {"field": "hours_per_week", "required": 15, "actual": 2})
            else:
                session["state"] = "WAITING_INPUT"
                _event(session, "agent-a", "HARD_CONSTRAINT_PASSED",
                       "陈予满足每周投入至少 15 小时的硬性要求。")
                _event(session, "agent-b", "TERMS_PROPOSED",
                       "陈予提出先试合作 14 天，并计划 90 天后全职加入。",
                       {"trial_days": 14, "start_in_days": 90})
                session["pending_question"] = {
                    "question_id": "start-in-days", "owner_id": "owner-a", "field": "start_in_days",
                    "title": "是否接受 90 天后全职加入？",
                    "reason": "陈予希望先进行 14 天试合作，且计划 90 天后全职加入。",
                    "options": [
                        {"value": "accept_90_days", "label": "接受 90 天后全职"},
                        {"value": "require_ai_experience", "label": "接受 90 天，但要求 AI 产品经验"},
                        {"value": "decline", "label": "不继续"},
                    ],
                    "scope": "session", "base_revision": 2,
                }
                _event(session, "system", "QUESTION_REQUESTED",
                       "需要林澈决定是否继续接受这一加入时间。",
                       {"question_id": "start-in-days", "owner_id": "owner-a"})
            db.execute("INSERT INTO sessions VALUES (?, ?)", (session_id, _canonical(session)))
            self._remember(db, owner_id, request["message_id"], route_key, request, session)
            return session

    def answer(self, session_id, owner_id, request):
        route_key = f"POST /api/sessions/{session_id}/answers"
        with self._transaction() as db:
            session = self._load(db, session_id)
            self._participant(session, owner_id)
            if owner_id != "owner-a":
                raise DomainError(403, "WRONG_OWNER", "此问题只允许林澈回答。")
            existing = self._existing(db, owner_id, request["message_id"], route_key, request)
            if existing is not None:
                return existing
            if session["revision"] != request["expected_revision"]:
                raise DomainError(409, "STALE_REVISION", "会话版本已变化，请刷新后重试。")
            if session["state"] != "WAITING_INPUT" or session["pending_question"] is None:
                raise DomainError(409, "INVALID_STATE", "当前没有待回答问题。")
            if session["pending_question"]["question_id"] != request["question_id"]:
                raise DomainError(422, "INVALID_QUESTION", "问题编号不匹配。")
            choice = request["answer"]
            session["pending_question"] = None
            session["revision"] += 1
            _event(session, "owner-a", "ANSWER_RECORDED", "林澈已回答待确认问题。",
                   {"answer": choice, "scope": "session"})
            if choice == "decline":
                session["state"] = "NO_MATCH"
                _event(session, "system", "NO_MATCH", "林澈决定不继续本次协商。")
            else:
                session["state"] = "NEGOTIATING"
                session["rounds"] += 1
                session["profile_versions"]["owner-a"] += 1
                if choice == "require_ai_experience":
                    session["terms"]["requires_ai_experience"] = True
                _event(session, "agent-a", "NEGOTIATING", "已在同一会话内恢复协商。",
                       {"session_profile_version": session["profile_versions"]["owner-a"]})
                if choice == "require_ai_experience":
                    _event(session, "agent-b", "EXPERIENCE_SELF_REPORTED",
                           "陈予自述具有 AI 产品经验；该信息尚未经独立核验。",
                           {"source": "self-reported", "ai_product_experience": True})
                digest = hashlib.sha256(_canonical({"session_id": session_id, "terms": session["terms"]}).encode()).hexdigest()
                session["proposal"] = {"version": 1, "digest": digest, "terms": dict(session["terms"])}
                session["state"] = "PENDING_APPROVAL"
                _event(session, "system", "PROPOSAL_READY", "协商条款已形成，等待双方分别批准。",
                       {"proposal_digest": digest})
            self._save(db, session)
            self._remember(db, owner_id, request["message_id"], route_key, request, session)
            return session

    def approve(self, session_id, owner_id, request):
        route_key = f"POST /api/sessions/{session_id}/approvals"
        with self._transaction() as db:
            session = self._load(db, session_id)
            self._participant(session, owner_id)
            existing = self._existing(db, owner_id, request["message_id"], route_key, request)
            if existing is not None:
                return existing
            if session["revision"] != request["expected_revision"]:
                raise DomainError(409, "STALE_REVISION", "会话版本已变化，请刷新后重试。")
            if session["state"] != "PENDING_APPROVAL" or session["proposal"] is None:
                raise DomainError(409, "INVALID_STATE", "当前没有可批准的提案。")
            if request["proposal_digest"] != session["proposal"]["digest"]:
                raise DomainError(409, "PROPOSAL_CHANGED", "提案摘要不匹配，请刷新后重试。")
            if any(item["owner_id"] == owner_id for item in session["approvals"]):
                raise DomainError(409, "ALREADY_DECIDED", "该参与者已决定。")
            session["approvals"].append({"owner_id": owner_id, "proposal_digest": request["proposal_digest"],
                                         "approve": request["approve"]})
            session["revision"] += 1
            if not request["approve"]:
                session["state"] = "DECLINED"
                _event(session, owner_id, "APPROVAL_DECLINED", "一方拒绝了本次提案；会话已结束。")
            else:
                _event(session, owner_id, "APPROVAL_GRANTED", "一方批准了本次提案。")
                if len(session["approvals"]) == 2:
                    session["state"] = "CONNECTED"
                    session["artifact"] = {
                        "session_id": session_id, "scenario_id": session["scenario_id"],
                        "terms": dict(session["terms"]), "consents": ["owner-a", "owner-b"],
                        "next_step": "双方自行确认试合作安排；本演示不交换联系方式。",
                        "mode": "deterministic",
                    }
                    _event(session, "system", "CONNECTED", "双方均已批准，形成试合作结果。")
            self._save(db, session)
            self._remember(db, owner_id, request["message_id"], route_key, request, session)
            return session

    def artifact(self, session_id, owner_id):
        session = self.get(session_id, owner_id)
        if session["state"] != "CONNECTED" or session["artifact"] is None:
            raise DomainError(409, "ARTIFACT_NOT_READY", "双方批准前无结果可查看。")
        return session["artifact"]
