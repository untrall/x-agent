from fastapi.testclient import TestClient
import pytest

from xagent.api import create_app


A = {"Authorization": "Bearer demo-owner-a"}
B = {"Authorization": "Bearer demo-owner-b"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "sessions.sqlite3")) as app:
        yield app


def start(client, candidate="agent-b", message_id="start-1"):
    return client.post(
        "/api/sessions",
        headers=A,
        json={"scenario_id": "cofounder.v1", "candidate_agent_id": candidate, "message_id": message_id},
    )


def answer(client, session, answer="accept_90_days", message_id="answer-1", **changes):
    body = {"question_id": session["pending_question"]["question_id"], "answer": answer,
            "expected_revision": session["revision"], "message_id": message_id, "scope": "session"}
    body.update(changes)
    return client.post(f"/api/sessions/{session['session_id']}/answers", headers=A, json=body)


def approve(client, session, headers=A, message_id="approve-a", **changes):
    body = {"proposal_digest": session["proposal"]["digest"], "approve": True,
            "expected_revision": session["revision"], "message_id": message_id}
    body.update(changes)
    return client.post(f"/api/sessions/{session['session_id']}/approvals", headers=headers, json=body)


def test_demo_and_pause_have_public_contract(client):
    demo = client.get("/api/demo")
    assert demo.status_code == 200
    assert demo.json()["scenario"] == {"id": "cofounder.v1", "name": "创业合伙人"}
    assert client.get("/api/health").json() == {"status": "ok", "mode": "deterministic"}
    response = start(client)
    assert response.status_code == 201
    session = response.json()
    assert session["state"] == "WAITING_INPUT"
    assert session["revision"] == 2
    assert session["rounds"] == 1
    assert session["pending_question"]["owner_id"] == "owner-a"
    assert session["pending_question"]["scope"] == "session"
    assert {option["value"] for option in session["pending_question"]["options"]} == {
        "accept_90_days", "require_ai_experience", "decline"}
    assert session["proposal"] is None and session["artifact"] is None
    assert all(event["session_id"] == session["session_id"] for event in session["events"])


def test_unknown_route_uses_error_contract(client):
    response = client.get("/api/absent")
    assert response.status_code == 404
    assert set(response.json()) == {"error"}


def test_conditional_experience_answer_keeps_evidence_self_reported(client):
    paused = start(client).json()
    proposal = answer(client, paused, answer="require_ai_experience").json()
    assert proposal["terms"]["requires_ai_experience"] is True
    assert proposal["profile_versions"] == {"owner-a": 2, "owner-b": 1}
    evidence = [event for event in proposal["events"] if event["type"] == "EXPERIENCE_SELF_REPORTED"]
    assert len(evidence) == 1
    assert evidence[0]["payload"]["source"] == "self-reported"
    assert client.get("/api/demo").json()["profiles"][0]["version"] == 1


def test_answer_resumes_same_session_and_survives_restart(client, tmp_path):
    paused = start(client).json()
    with TestClient(create_app(tmp_path / "sessions.sqlite3")) as restarted_while_paused:
        assert restarted_while_paused.get(f"/api/sessions/{paused['session_id']}", headers=A).json() == paused
        result = answer(restarted_while_paused, paused).json()
    assert result["session_id"] == paused["session_id"]
    assert result["state"] == "PENDING_APPROVAL"
    assert result["revision"] > paused["revision"]
    assert result["profile_versions"] == {"owner-a": 2, "owner-b": 1}
    assert result["pending_question"] is None
    assert result["proposal"]["terms"]["start_in_days"] == 90
    assert any(event["type"] == "NEGOTIATING" for event in result["events"])
    with TestClient(create_app(tmp_path / "sessions.sqlite3")) as restarted:
        loaded = restarted.get(f"/api/sessions/{paused['session_id']}", headers=B)
        assert loaded.status_code == 200
        assert loaded.json() == result
        assert answer(restarted, paused).json() == result
        assert restarted.get("/api/demo").json()["profiles"][0]["version"] == 1


def test_auth_owner_and_shape_validation(client):
    paused = start(client).json()
    path = f"/api/sessions/{paused['session_id']}/answers"
    assert client.get(f"/api/sessions/{paused['session_id']}").status_code == 401
    assert client.get(f"/api/sessions/{paused['session_id']}", headers={"Authorization": "Bearer stranger"}).status_code == 401
    assert client.post(path, headers=B, json={"question_id": "start-in-days", "answer": "decline",
        "expected_revision": 2, "message_id": "wrong-owner", "scope": "session"}).status_code == 403
    assert answer(client, paused, answer="anything").status_code == 422
    assert answer(client, paused, scope="global").status_code == 422
    assert answer(client, paused, extra="unexpected").status_code == 422
    assert answer(client, paused, expected_revision="2").status_code == 422
    assert client.get(f"/api/sessions/{paused['session_id']}", headers=A).json() == paused


def test_answer_revision_and_idempotency(client):
    paused = start(client).json()
    assert answer(client, paused, expected_revision=1).status_code == 409
    first = answer(client, paused)
    assert first.status_code == 200
    assert answer(client, paused).json() == first.json()
    assert answer(client, paused, answer="decline").status_code == 409
    assert answer(client, paused, message_id="new-stale").status_code == 409


def test_hard_reject_and_decline_are_terminal(client):
    rejected = start(client, "agent-c").json()
    assert rejected["state"] == "NO_MATCH"
    assert rejected["pending_question"] is None
    assert rejected["proposal"] is None
    assert client.get(f"/api/sessions/{rejected['session_id']}", headers=B).status_code == 403
    paused = start(client, message_id="start-2").json()
    declined = answer(client, paused, answer="decline").json()
    assert declined["state"] == "NO_MATCH"
    assert declined["profile_versions"] == {"owner-a": 1, "owner-b": 1}
    assert answer(client, paused, message_id="another").status_code == 409


def test_approval_requires_same_digest_then_both_consent(client):
    paused = start(client).json()
    proposal = answer(client, paused).json()
    path = f"/api/sessions/{proposal['session_id']}/artifact"
    assert client.get(path, headers=A).status_code == 409
    assert approve(client, proposal, proposal_digest="wrong").status_code == 409
    first = approve(client, proposal).json()
    assert first["state"] == "PENDING_APPROVAL"
    assert first["approvals"] == [{"owner_id": "owner-a", "proposal_digest": proposal["proposal"]["digest"], "approve": True}]
    assert approve(client, proposal).json() == first
    assert approve(client, proposal, headers=B, message_id="approve-b", expected_revision=proposal["revision"]).status_code == 409
    connected = approve(client, first, headers=B, message_id="approve-b").json()
    assert connected["state"] == "CONNECTED"
    assert connected["artifact"]["session_id"] == paused["session_id"]
    assert connected["artifact"]["consents"] == ["owner-a", "owner-b"]
    assert client.get(path, headers=B).json() == connected["artifact"]
    assert approve(client, connected, headers=B, message_id="again").status_code == 409


def test_approval_rejection_is_terminal(client):
    paused = start(client).json()
    proposal = answer(client, paused).json()
    declined = approve(client, proposal, headers=B, message_id="no-b", approve=False).json()
    assert declined["state"] == "DECLINED"
    assert declined["artifact"] is None
    assert approve(client, declined, message_id="later").status_code == 409


def test_create_idempotency_does_not_duplicate_session(client):
    first = start(client)
    assert first.status_code == 201
    assert start(client).json() == first.json()
    assert start(client, "agent-c").status_code == 409
