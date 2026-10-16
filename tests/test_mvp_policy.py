"""Policy boundary tests for explicit evidence and provider JSON responses."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from xagent.mvp.policy import DeterministicPolicy, ModelPolicy, PolicyError


SCENARIO = {
    "id": "venue", "name": "Venue",
    "fields": {
        "capacity": {"label": "Capacity", "type": "number", "aliases": ["人数", "seats"]},
        "projector": {"label": "Projector", "type": "boolean", "aliases": ["投影仪"]},
        "district": {"label": "District", "type": "string", "aliases": ["区域"], "pattern": r"位于(?P<value>[^，,;； ]+)"},
    },
    "followup": {"field": "projector", "title": "Projector needed?", "prompt": "Do you need a projector?"},
}


def run(coro):
    return asyncio.run(coro)


def test_extract_only_expressed_requirements_and_scenario_aliases():
    policy = DeterministicPolicy()
    got = run(policy.extract("人数>=30, 投影仪=true; 位于徐汇", SCENARIO))
    assert got == [
        {"field": "capacity", "op": "gte", "value": 30},
        {"field": "projector", "op": "eq", "value": True},
        {"field": "district", "op": "eq", "value": "徐汇"},
    ]
    assert run(policy.extract("Find me a great place", SCENARIO)) == []


def test_explicit_comparator_wins_over_overlapping_scenario_pattern():
    scenario = {"fields": {"capacity": {"type": "number", "aliases": [],
                                      "pattern": r"capacity\s*(?:>=|=)\s*(\d+)", "default_op": "gte"}}}
    assert run(DeterministicPolicy().extract("capacity=30", scenario)) == [
        {"field": "capacity", "op": "eq", "value": 30}
    ]


def test_unknown_required_fact_asks_owner_and_hard_fail_rejects():
    policy = DeterministicPolicy()
    base = {
        "scenario": SCENARIO, "role": "provider", "stage": "evaluate",
        "requirements": [{"field": "capacity", "op": "gte", "value": 30}],
        "own_facts": {}, "peer_facts": {}, "history": [], "memory": {},
    }
    unknown = run(policy.decide({**base, "evaluation": {"status": "UNKNOWN", "unknown_fields": ["capacity"], "reasons": []}}))
    assert unknown["action"] == "ASK_OWNER"
    assert unknown["field"] == "capacity"
    failed = run(policy.decide({**base, "evaluation": {"status": "FAIL", "unknown_fields": [], "reasons": []}}))
    assert failed["action"] == "REJECT"
    assert failed["facts"] == {}


def test_requester_uses_pass_attestation_without_private_fact():
    result = run(DeterministicPolicy().decide({
        "scenario": SCENARIO, "role": "requester", "stage": "evaluate",
        "requirements": [{"field": "capacity", "op": "gte", "value": 30}],
        "own_facts": {}, "peer_facts": {}, "history": [], "memory": {},
        "evaluation": {"status": "PASS", "unknown_fields": [], "reasons": []},
    }))
    assert result["action"] == "PROPOSE"
    assert result["facts"] == {}


class FixtureHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        self.requests.append(json.loads(self.rfile.read(size)))
        response = self.responses.pop(0)
        status, body = response[:2]
        if len(response) > 2:
            time.sleep(response[2])
        payload = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        pass


@pytest.fixture
def provider_server():
    FixtureHandler.responses = []
    FixtureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def completion(content, usage=None):
    return {"choices": [{"message": {"content": content}}], "usage": usage or {}}


def valid_decision():
    return {"action": "WAIT", "summary": "Awaiting owner", "field": None, "question": None, "facts": {}, "terms": {}}


def test_model_decision_schema_and_usage(provider_server):
    FixtureHandler.responses = [(200, completion(json.dumps(valid_decision()), {"total_tokens": 23}))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    got = run(policy.decide({"scenario": SCENARIO, "role": "provider", "stage": "evaluate", "requirements": [], "own_facts": {}, "peer_facts": {}, "history": [], "memory": {}}))
    assert got == valid_decision()
    assert policy.last_usage["total_tokens"] == 23
    assert FixtureHandler.requests[0]["model"] == "fixture"


def test_model_repair_once_then_rejects_invalid_action(provider_server):
    bad = {**valid_decision(), "action": "OWNER_APPROVAL"}
    FixtureHandler.responses = [(200, completion(json.dumps(bad))), (200, completion(json.dumps(bad)))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    with pytest.raises(PolicyError, match="action"):
        run(policy.decide({"scenario": SCENARIO, "role": "provider", "stage": "evaluate", "requirements": [], "own_facts": {}, "peer_facts": {}, "history": [], "memory": {}}))
    assert len(FixtureHandler.requests) == 2


def test_model_refusal_and_http_error_are_explicit(provider_server):
    FixtureHandler.responses = [(200, {"choices": [{"message": {"refusal": "No"}}]})]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    with pytest.raises(PolicyError, match="refus"):
        run(policy.extract("capacity>=30", SCENARIO))
    FixtureHandler.responses = [(503, {"error": "down"})]
    with pytest.raises(PolicyError, match="HTTP 503"):
        run(policy.extract("capacity>=30", SCENARIO))


def test_model_timeout_is_visible_without_deterministic_fallback(provider_server):
    FixtureHandler.responses = [(200, completion('{"requirements":[]}'), 0.2)]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic", timeout=0.05)
    with pytest.raises(PolicyError, match="timeout"):
        run(policy.extract("capacity>=30", SCENARIO))


def test_model_rejects_fabricated_fact_even_with_pass_evaluation(provider_server):
    decision = {**valid_decision(), "action": "PROPOSE", "facts": {"capacity": 999}}
    FixtureHandler.responses = [(200, completion(json.dumps(decision))), (200, completion(json.dumps(decision)))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    context = {"scenario": SCENARIO, "role": "provider", "stage": "evaluate", "requirements": [],
               "own_facts": {"capacity": 30}, "peer_facts": {}, "public_fields": ["capacity"],
               "history": [], "memory": {}, "evaluation": {"status": "PASS"}}
    with pytest.raises(PolicyError, match="own-source evidence"):
        run(policy.decide(context))


def test_model_extract_requires_typed_values(provider_server):
    wrong_type = {"requirements": [{"field": "capacity", "op": "gte", "value": "30"}]}
    FixtureHandler.responses = [(200, completion(json.dumps(wrong_type))), (200, completion(json.dumps(wrong_type)))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    with pytest.raises(PolicyError, match="number value must be numeric"):
        run(policy.extract("capacity>=30", SCENARIO))


def test_model_unhashable_schema_value_is_reported_as_policy_error(provider_server):
    malformed = {**valid_decision(), "action": ["PROPOSE"]}
    FixtureHandler.responses = [(200, completion(json.dumps(malformed))), (200, completion(json.dumps(malformed)))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    context = {"scenario": SCENARIO, "role": "provider", "stage": "evaluate", "requirements": [],
               "own_facts": {}, "peer_facts": {}, "history": [], "memory": {},
               "evaluation": {"status": "PASS"}}
    with pytest.raises(PolicyError, match="invalid action"):
        run(policy.decide(context))


def test_model_malformed_response_envelope_is_reported(provider_server):
    FixtureHandler.responses = [(200, {"choices": [{"message": []}]}),
                                (200, {"choices": [{"message": []}]})]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    with pytest.raises(PolicyError, match="response envelope"):
        run(policy.extract("capacity>=30", SCENARIO))


def test_model_repair_uses_stage_allowed_actions(provider_server):
    proposed = {**valid_decision(), "action": "PROPOSE", "summary": "Conditions pass"}
    FixtureHandler.responses = [(200, completion(json.dumps(valid_decision()))),
                                (200, completion(json.dumps(proposed)))]
    policy = ModelPolicy(base_url=provider_server, model="fixture", api_key="synthetic")
    context = {"scenario": SCENARIO, "role": "requester", "stage": "evaluate", "requirements": [],
               "own_facts": {}, "peer_facts": {}, "history": [], "memory": {},
               "evaluation": {"status": "PASS"}, "allowed_actions": ["PROPOSE", "REJECT"]}
    assert run(policy.decide(context))["action"] == "PROPOSE"
    assert len(FixtureHandler.requests) == 2
    assert "PROPOSE" in FixtureHandler.requests[0]["messages"][0]["content"]
    assert "REJECT" in FixtureHandler.requests[0]["messages"][0]["content"]


def test_http_interprets_natural_answer_as_typed_fact(provider_server):
    answer = {'status':'resolved', 'value':80, 'clarification':None}
    FixtureHandler.responses = [(200, completion(json.dumps(answer)))]
    policy = ModelPolicy(base_url=provider_server, model='fixture', api_key='synthetic')
    assert run(policy.interpret_answer('场地能坐八十个人', {'field':'capacity','scope':'session','kind':'fact'}, SCENARIO)) == answer
