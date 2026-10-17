"""Choice-stage chat: requester asks, provider's own agent answers from persona."""

import pytest

from xagent.mvp.chat import ChatError, ChatModel
from xagent.mvp.runtime import AgentRuntime

from test_mvp_core import TestPolicy, config


class FakeChat:
    model = "fake-model"

    def __init__(self, reply="周末喜欢去江边跑步。", error=None):
        self.reply_text, self.error, self.calls = reply, error, []

    async def reply(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply_text


def pending_session(runtime, session_id, peer, role):
    session = runtime._new_session(session_id, "r-1", peer, role, [])
    session["state"] = "PENDING_APPROVAL"
    session["proposal"] = {"digest": f"d-{session_id}", "version": 1,
                           "terms": {"requirements": [], "provider_facts": {}}}
    runtime.storage.put("session", session_id, session)
    return session


def pair(tmp_path, chat_model=None):
    requester = AgentRuntime(config(tmp_path, "azhe", ["yutong"]), policy=TestPolicy())
    cfg = config(tmp_path, "yutong", ["azhe"])
    cfg["profile"]["persona"] = {"name": "yutong", "interests": ["跑步"]}
    provider = AgentRuntime(cfg, policy=TestPolicy(), chat_model=chat_model)
    pending_session(requester, "s-1", "yutong", "requester")
    pending_session(provider, "s-1", "azhe", "provider")
    return requester, provider


async def deliver(sender, receiver, kind):
    """Move the newest queued envelope of `kind` and process it."""
    item = [o for o in sender.storage.pending_outbox() if o["envelope"]["type"] == kind][-1]
    envelope = item["envelope"]
    sender.storage.delivered(item["message_id"])
    assert receiver.receive(envelope, envelope["sender_agent_id"])
    await receiver._process(envelope)


def events(runtime, kind):
    return [e for e in runtime.storage.events() if e["type"] == kind]


@pytest.mark.asyncio
async def test_chat_round_trip_answers_from_providers_own_persona(tmp_path):
    brain = FakeChat()
    requester, provider = pair(tmp_path, brain)
    await requester.chat("s-1", "她周末一般怎么过？")
    await deliver(requester, provider, "CHAT")
    await deliver(provider, requester, "CHAT_REPLY")
    assert events(requester, "CHAT_SENT")[0]["summary"] == "她周末一般怎么过？"
    reply = events(requester, "CHAT_REPLY")[0]
    assert reply["summary"] == "周末喜欢去江边跑步。" and reply["payload"]["ok"] is True
    assert events(provider, "CHAT_RECEIVED")[0]["summary"] == "她周末一般怎么过？"
    call = brain.calls[0]
    assert call["persona"] == {"name": "yutong", "interests": ["跑步"]}
    assert call["name"] == "yutong" and call["peer"] == "azhe"
    # Chat never touches negotiation state.
    session = provider.storage.get("session", "s-1")
    assert session["state"] == "PENDING_APPROVAL" and session["approvals"] == []


@pytest.mark.asyncio
async def test_follow_up_question_carries_previous_turns(tmp_path):
    brain = FakeChat()
    requester, provider = pair(tmp_path, brain)
    for text in ("周末怎么过？", "那平时呢？"):
        await requester.chat("s-1", text)
        await deliver(requester, provider, "CHAT")
        await deliver(provider, requester, "CHAT_REPLY")
    assert brain.calls[1]["history"] == [{"question": "周末怎么过？", "reply": "周末喜欢去江边跑步。"}]


@pytest.mark.asyncio
async def test_model_failure_still_replies_and_is_marked_not_ok(tmp_path):
    requester, provider = pair(tmp_path, FakeChat(error=ChatError("模型超时（30s）")))
    await requester.chat("s-1", "在吗？")
    await deliver(requester, provider, "CHAT")
    await deliver(provider, requester, "CHAT_REPLY")
    reply = events(requester, "CHAT_REPLY")[0]
    assert reply["payload"]["ok"] is False and "模型超时" in reply["summary"]


@pytest.mark.asyncio
async def test_provider_without_chat_model_says_so(tmp_path):
    requester, provider = pair(tmp_path, None)
    await requester.chat("s-1", "在吗？")
    await deliver(requester, provider, "CHAT")
    reply = events(provider, "CHAT_REPLIED")[0]
    assert reply["payload"]["ok"] is False and "没有连接聊天模型" in reply["summary"]


@pytest.mark.asyncio
async def test_chat_only_from_requester_at_pending_approval(tmp_path):
    requester, provider = pair(tmp_path, FakeChat())
    with pytest.raises(ValueError, match="只能和自己发起需求"):
        await provider.chat("s-1", "我也想问")
    with pytest.raises(ValueError, match="不能为空"):
        await requester.chat("s-1", "  ")
    with pytest.raises(ValueError, match="不能超过"):
        await requester.chat("s-1", "长" * 301)
    session = requester.storage.get("session", "s-1")
    session["state"] = "ACTIVE"
    requester.storage.put("session", "s-1", session)
    with pytest.raises(ValueError, match="待你确认"):
        await requester.chat("s-1", "现在能聊吗？")


@pytest.mark.asyncio
async def test_chat_reply_cannot_be_sent_to_provider(tmp_path):
    requester, provider = pair(tmp_path, FakeChat())
    reverse = requester._envelope(requester.storage.get("session", "s-1"), "CHAT_REPLY",
                                  {"chat_id": "c", "text": "伪造", "ok": True})
    provider.receive(reverse, "azhe")
    with pytest.raises(PermissionError):
        await provider._process(reverse)


def peer_envelope(sender, session_id, kind, payload):
    from xagent.mvp.models import new_id
    return {"schema_version": 1, "message_id": new_id(), "request_id": "r-1", "session_id": session_id,
            "sender_agent_id": sender, "recipient_agent_id": "azhe", "type": kind,
            "causation_id": None, "payload": payload}


def three_pending(tmp_path):
    runtime = AgentRuntime(config(tmp_path, "azhe", ["a", "b", "c"]), policy=TestPolicy())
    for sid, peer in (("s-a", "a"), ("s-b", "b"), ("s-c", "c")):
        pending_session(runtime, sid, peer, "requester")
    return runtime


def states(runtime):
    return {s["session_id"]: s["state"] for s in runtime.snapshot()["sessions"]}


@pytest.mark.asyncio
async def test_choose_asks_the_chosen_one_and_keeps_the_rest_waiting(tmp_path):
    runtime = three_pending(tmp_path)
    await runtime.choose("s-b")
    sessions = {s["session_id"]: s for s in runtime.snapshot()["sessions"]}
    assert sessions["s-b"]["approvals"] == ["azhe"]
    assert states(runtime) == {"s-a": "PENDING_APPROVAL", "s-b": "PENDING_APPROVAL", "s-c": "PENDING_APPROVAL"}
    with pytest.raises(ValueError, match="正在等待 b 回应"):
        await runtime.choose("s-a")


@pytest.mark.asyncio
async def test_acceptance_connects_and_only_then_declines_the_rest(tmp_path):
    runtime = three_pending(tmp_path)
    await runtime.choose("s-b")
    envelope = peer_envelope("b", "s-b", "APPROVAL", {"digest": "d-s-b"})
    runtime.receive(envelope, "b")
    await runtime._process(envelope)
    assert states(runtime) == {"s-a": "REJECTED", "s-b": "CONNECTED", "s-c": "REJECTED"}
    rejects = [o["envelope"] for o in runtime.storage.pending_outbox() if o["envelope"]["type"] == "REJECT"]
    assert {e["recipient_agent_id"] for e in rejects} == {"a", "c"}
    assert all(e["payload"]["reason"] == "owner rejected proposal" for e in rejects)


@pytest.mark.asyncio
async def test_decline_by_chosen_one_lets_owner_choose_again(tmp_path):
    runtime = three_pending(tmp_path)
    await runtime.choose("s-b")
    envelope = peer_envelope("b", "s-b", "REJECT", {"reason": "owner rejected proposal", "digest": "d-s-b"})
    runtime.receive(envelope, "b")
    await runtime._process(envelope)
    assert states(runtime) == {"s-a": "PENDING_APPROVAL", "s-b": "NO_MATCH", "s-c": "PENDING_APPROVAL"}
    await runtime.choose("s-c")
    assert "azhe" in runtime.storage.get("session", "s-c")["approvals"]


def test_chat_model_reads_llm_env_fallback(monkeypatch):
    for key in ("XAGENT_MODEL_BASE_URL", "XAGENT_MODEL_NAME", "XAGENT_MODEL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "glm-test")
    monkeypatch.setenv("LLM_API_KEY", "k")
    model = ChatModel.from_env()
    assert model.model == "glm-test" and model.base_url == "https://example.test/v1"
    monkeypatch.delenv("LLM_API_KEY")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        ChatModel.from_env()
