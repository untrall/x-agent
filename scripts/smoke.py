"""Exercise the live deterministic HTTP flow from pause to artifact."""

import argparse
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4


def call(base_url, method, path, owner=None, body=None):
    headers = {"Content-Type": "application/json"}
    if owner:
        headers["Authorization"] = f"Bearer demo-{owner}"
    data = json.dumps(body).encode() if body is not None else None
    request = Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["deterministic"], default="deterministic")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    nonce = uuid4().hex
    status, health = call(base, "GET", "/api/health")
    assert status == 200 and health == {"status": "ok", "mode": "deterministic"}
    status, paused = call(base, "POST", "/api/sessions", "owner-a", {
        "scenario_id": "cofounder.v1", "candidate_agent_id": "agent-b", "message_id": f"smoke-start-{nonce}"})
    assert status == 201 and paused["state"] == "WAITING_INPUT"
    session_id = paused["session_id"]
    status, proposal = call(base, "POST", f"/api/sessions/{session_id}/answers", "owner-a", {
        "question_id": paused["pending_question"]["question_id"], "answer": "accept_90_days",
        "expected_revision": paused["revision"], "message_id": f"smoke-answer-{nonce}", "scope": "session"})
    assert status == 200 and proposal["state"] == "PENDING_APPROVAL" and proposal["session_id"] == session_id
    for owner in ("owner-a", "owner-b"):
        status, proposal = call(base, "POST", f"/api/sessions/{session_id}/approvals", owner, {
            "proposal_digest": proposal["proposal"]["digest"], "approve": True,
            "expected_revision": proposal["revision"], "message_id": f"smoke-{owner}-{nonce}"})
        assert status == 200
    assert proposal["state"] == "CONNECTED"
    status, artifact = call(base, "GET", f"/api/sessions/{session_id}/artifact", "owner-b")
    assert status == 200 and artifact["session_id"] == session_id
    print(f"OK deterministic HTTP flow: {session_id}, {len(proposal['events'])} events, artifact ready")


if __name__ == "__main__":
    main()
