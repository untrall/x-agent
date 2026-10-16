"""Acceptance against independent OS processes and actual loopback HTTP."""

import pytest
from scripts.smoke_mvp import Cluster, run_demo


@pytest.fixture
def cluster(tmp_path):
    group = Cluster(tmp_path)
    try:
        for number in range(1, 5):
            group.start(number)
        yield group
    finally:
        group.close()


def test_four_processes_filter_loopback_restart_and_dual_approval(cluster):
    run_demo(cluster)


def test_venue_uses_identical_processes_with_different_config(tmp_path):
    group = Cluster(tmp_path, "venue", {
        1: {"capacity": 100}, 2: {"capacity": 10},
        3: {"capacity": 80}, 4: {"capacity": 60},
    })
    try:
        for number in range(1, 5):
            group.start(number)
        result = run_demo(group, "寻找活动场地，容量50")
        assert result["scenario"] == "venue"
    finally:
        group.close()


def test_answers_determine_winner_instead_of_candidate_id(cluster):
    c = cluster
    c.call(1, "POST", "/owner/requests", {"text": "寻找创业合伙人，每周至少15小时"})
    c.answer(1, c.wait(lambda: c.pending(1), "requester question")[0], "是")
    c.answer(3, c.wait(lambda: c.pending(3), "provider 3 question")[0], "否")
    c.answer(4, c.wait(lambda: c.pending(4), "provider 4 question")[0], "是")
    c.wait(lambda: c.pair(1, "agent-3")["state"] == "NO_MATCH", "3 rejected by facts")
    c.wait(lambda: c.pair(1, "agent-4")["state"] == "PENDING_APPROVAL", "4 qualifies by facts")


def test_confirmed_memory_is_reused_after_restart_in_a_new_session(cluster):
    c = cluster
    c.call(1, "POST", "/owner/requests", {"text": "寻找创业合伙人，每周至少15小时"})
    c.answer(1, c.wait(lambda: c.pending(1), "requester question")[0], "是")
    q3 = c.wait(lambda: c.pending(3), "provider question")[0]
    c.call(3, "POST", "/owner/answers", {
        "question_id": q3["question_id"], "text": "是", "remember": True,
        "expected_revision": q3["revision"],
    })
    c.wait(lambda: c.pair(1, "agent-3")["state"] == "PENDING_APPROVAL", "first proposal")
    c.stop(3)
    c.start(3)
    second = c.call(1, "POST", "/owner/requests", {
        "text": "新一轮合伙人需求",
        "requirements": [
            {"field": "weekly_hours", "op": "gte", "value": 15},
            {"field": "ai_product_experience", "op": "eq", "value": True},
        ],
    })
    def new_pair():
        return next((s for s in c.state(1)["sessions"] if s["request_id"] == second["request_id"] and s["peer_id"] == "agent-3"), None)
    c.wait(lambda: new_pair() and new_pair()["state"] == "PENDING_APPROVAL", "memory reused without another question")
    assert not [q for q in c.pending(3) if q["request_id"] == second["request_id"]]
    assert new_pair()["session_id"] != c.pair(1, "agent-3")["session_id"]


def test_model_http_adapter_drives_four_real_processes(tmp_path):
    """Fake provider, real model adapter and real agent HTTP; no live LLM claim."""
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.loads(body["messages"][1]["content"])
            calls.append(data)
            time.sleep(.08)  # Make policy awaits real, exposing coalescing races.
            if "answer" in data:
                output = {"status": "resolved", "value": data['answer'] == '是', "clarification": None}
            elif "stage" not in data:
                output = {"requirements": [{"field": "weekly_hours", "op": "gte", "value": 15}]}
            else:
                output = {"action": "PROPOSE", "summary": f"MODEL-HTTP-FIXTURE:{data['stage']}",
                          "field": None, "question": None, "facts": {}, "terms": {}}
                if data["stage"] == "followup":
                    output.update(action="ASK_OWNER", field="ai_product_experience", question="是否要求 AI 产品经验？")
                elif data["evaluation"]["status"] == "UNKNOWN":
                    output.update(action="ASK_OWNER", field=data["evaluation"]["unknown_fields"][0], question="是否有 AI 产品经验？")
                elif data["evaluation"]["status"] == "FAIL":
                    output["action"] = "REJECT"
                elif data["stage"] == "proposal":
                    output["action"] = "ACCEPT"
            payload = json.dumps({"choices": [{"message": {"content": json.dumps(output)}}],
                                  "usage": {"total_tokens": 11}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    group = Cluster(tmp_path, mode="model", model_env={
        "XAGENT_MODEL_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "XAGENT_MODEL_NAME": "local-http-fixture",
        "XAGENT_MODEL_API_KEY": "synthetic-test-only",
    })
    try:
        for number in range(1, 5):
            group.start(number)
        run_demo(group)
        assert sorted(call['answer'] for call in calls if 'answer' in call) == ['否', '是', '是']
        assert all(group.state(n)["mode"] == "model" for n in range(1, 5))
        assert not [call for call in calls if call.get("own_facts", {}).get("weekly_hours") == 2]
        assert len([q for q in group.state(1)["questions"] if q["scope"] == "request"]) == 1
        for number in (1, 3):
            assert "MODEL-HTTP-FIXTURE" in json.dumps(group.state(number)["events"])
    finally:
        group.close()
        server.shutdown()
        thread.join()
        server.server_close()
