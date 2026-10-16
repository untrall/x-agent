import httpx
import pytest

from xagent.mvp.runtime import AgentRuntime
from xagent.mvp.server import create_peer_app
from test_mvp_core import SCENARIO, TestPolicy, config


@pytest.mark.asyncio
async def test_owner_and_peer_http_authentication_and_durable_ack(tmp_path):
    runtime = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], scenario=SCENARIO), policy=TestPolicy())
    app = create_peer_app(runtime)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/owner/state")).status_code == 401
        assert (await client.get("/owner/state", headers={"Authorization": "Bearer token-requester-z"})).status_code == 401
        assert (await client.get("/owner/state", headers={"Authorization": "Bearer token-provider-z"})).status_code == 401
        assert (await client.get("/owner/state", headers={"Authorization": "Bearer owner-token-provider-z"})).status_code == 200
        message = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                   "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                   "payload": {"scenario_id": "generic", "text": "need", "requirements": []}}
        assert (await client.post("/messages", json=message, headers={"Authorization": "Bearer token-provider-z"})).status_code == 401
        sent = await client.post("/messages", json=message, headers={"Authorization": "Bearer token-requester-z"})
        assert sent.status_code == 200 and sent.json()["accepted"] is True
        repeat = await client.post("/messages", json=message, headers={"Authorization": "Bearer token-requester-z"})
        assert repeat.status_code == 200 and repeat.json()["accepted"] is False
        assert len(runtime.storage.pending_inbox()) == 1
        malformed = {**message, "message_id": "m-2", "payload": {"scenario_id": "generic", "requirements": "wrong"}}
        assert (await client.post("/messages", json=malformed, headers={"Authorization": "Bearer token-requester-z"})).status_code == 409
        assert len(runtime.storage.pending_inbox()) == 1
