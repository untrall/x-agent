import pytest
import asyncio

from xagent.mvp.scenario import evaluate_requirements, validate_scenario
from xagent.mvp.runtime import AgentRuntime
from xagent.mvp.models import proposal_digest
from xagent.mvp.storage import Storage


SCENARIO = {
    "id": "generic",
    "name": "Generic",
    "fields": {
        "hours": {"label": "Hours", "type": "number", "aliases": []},
        "remote": {"label": "Remote", "type": "boolean", "aliases": []},
        "skills": {"label": "Skills", "type": "string", "aliases": []},
    },
    "initial_requirements": [],
    "result_title": "Result",
}


def test_real_constraints_distinguish_pass_fail_and_unknown():
    scenario = validate_scenario(SCENARIO)
    requirements = [
        {"field": "hours", "op": "gte", "value": 18},
        {"field": "remote", "op": "eq", "value": True},
    ]
    assert evaluate_requirements(requirements, {"hours": 20, "remote": True}, scenario)["status"] == "PASS"
    failed = evaluate_requirements(requirements, {"hours": 10, "remote": True}, scenario)
    assert failed["status"] == "FAIL"
    assert failed["reasons"][0]["field"] == "hours"
    assert failed["reasons"][0]["status"] == "FAIL"
    unknown = evaluate_requirements(requirements, {"hours": 20}, scenario)
    assert unknown["status"] == "UNKNOWN"
    assert unknown["unknown_fields"] == ["remote"]


def test_second_scenario_uses_same_rule_engine():
    venue = {
        "id": "venue",
        "name": "Venue",
        "fields": {"capacity": {"label": "Capacity", "type": "number", "aliases": []}},
        "initial_requirements": [],
        "result_title": "Venue result",
    }
    result = evaluate_requirements([{"field": "capacity", "op": "gte", "value": 50}], {"capacity": 80}, validate_scenario(venue))
    assert result["status"] == "PASS"


def test_unsupported_constraint_rejected():
    scenario = validate_scenario(SCENARIO)
    with pytest.raises(ValueError, match="operator"):
        evaluate_requirements([{"field": "hours", "op": "contains", "value": "2"}], {"hours": 20}, scenario)


class TestPolicy:
    mode = "deterministic"

    async def extract(self, text, scenario):
        return [{"field": "hours", "op": "gte", "value": 18}]

    async def decide(self, context):
        status = context["evaluation"]["status"]
        if status == "FAIL":
            action = "REJECT"
        elif status == "UNKNOWN":
            action = "ASK_OWNER" if context["role"] == "provider" else "ASK_PEER"
        else:
            action = "ACCEPT" if context["stage"] == "proposal" else "PROPOSE"
        return {"action": action, "summary": action, "field": (context["evaluation"]["unknown_fields"] or [None])[0], "question": None, "facts": {}, "terms": {}}


def config(tmp_path, agent_id, peers=(), facts=None, scenario=SCENARIO):
    return {
        "agent_id": agent_id, "owner_id": f"owner-{agent_id}", "name": agent_id,
        "host": "127.0.0.1", "port": 0, "database": str(tmp_path / f"{agent_id}.sqlite3"),
        "token": f"token-{agent_id}", "owner_token": f"owner-token-{agent_id}", "scenario": scenario,
        "profile": {"facts": facts or {}, "public_fields": list(scenario["fields"]), "tags": []},
        "peers": [{"agent_id": peer, "name": peer, "url": "http://127.0.0.1:1", "token": f"token-{peer}"} for peer in peers],
    }


@pytest.mark.asyncio
async def test_policy_uses_profile_description_and_confirmed_memory_as_context(tmp_path):
    class Capture(TestPolicy):
        async def decide(self, context):
            self.context = context
            return await super().decide(context)
    brain = Capture()
    cfg = config(tmp_path, 'owner', ['peer'], facts={'hours':20, 'private_note':'secret'})
    cfg['profile']['description'] = '独立产品设计师'
    runtime = AgentRuntime(cfg, policy=brain)
    runtime.storage.put('memory', 'facts', {'hours':35})
    await runtime.broadcast('Need collaboration', requirements=[])
    session = runtime.snapshot()['sessions'][0]
    await runtime._decide(session, 'evaluate', {'status':'PASS','unknown_fields':[], 'reasons':[]})
    view = brain.context['own_profile']
    assert view['description'] == '独立产品设计师'
    assert view['facts']['hours'] == 35
    assert '35' in view['summary']
    assert 'secret' not in view['summary']
    assert brain.context['own_facts']['hours'] == 35


@pytest.mark.asyncio
async def test_broadcast_creates_independent_sessions_and_durable_outbox(tmp_path):
    runtime = AgentRuntime(config(tmp_path, "arbitrary-requester", ["person-x", "person-y"]), policy=TestPolicy())
    created = await runtime.broadcast("Need 18 hours", [{"field": "hours", "op": "gte", "value": 18}])
    snap = runtime.snapshot()
    assert len(created["session_ids"]) == 2
    assert {s["peer_id"] for s in snap["sessions"]} == {"person-x", "person-y"}
    assert {row["type"] for row in runtime.storage.pending_outbox()} == {"REQUEST"}
    restarted = AgentRuntime(runtime.config, policy=TestPolicy())
    assert len(restarted.storage.pending_outbox()) == 2
    assert {s["session_id"] for s in restarted.snapshot()["sessions"]} == set(created["session_ids"])


async def eventually(predicate):
    for _ in range(100):
        value = predicate()
        if value:
            return value
        await asyncio.sleep(.02)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
async def test_unknown_provider_fact_survives_restart_and_answer_resumes(tmp_path):
    receiver = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 20}), policy=TestPolicy())
    envelope = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                "payload": {"scenario_id": "generic", "text": "remote", "requirements": [{"field": "remote", "op": "eq", "value": True}]}}
    assert receiver.receive(envelope, "requester-z") is True
    assert receiver.receive(envelope, "requester-z") is False
    await receiver.start()
    question = (await eventually(lambda: [q for q in receiver.snapshot()["questions"] if not q["answered"]]))[0]
    assert receiver.snapshot()["sessions"][0]["state"] == "WAITING_INPUT"
    await receiver.stop()
    restarted = AgentRuntime(receiver.config, policy=TestPolicy())
    assert restarted.snapshot()["questions"][0]["question_id"] == question["question_id"]
    await restarted.answer(question["question_id"], "yes", remember=True, expected_revision=question["revision"])
    assert restarted.snapshot()["questions"][0]["answered"] is True
    assert restarted.snapshot()["sessions"][0]["state"] == "ACTIVE"
    assert restarted.snapshot()["memory"] == {"remote": True}
    assert [row["type"] for row in restarted.storage.queued_outbox()].count("FILTER") == 2


@pytest.mark.asyncio
async def test_wrong_pair_message_rejected_before_durable_ack(tmp_path):
    receiver = AgentRuntime(config(tmp_path, "provider-z", ["requester-z", "other-z"]), policy=TestPolicy())
    original = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                "payload": {"scenario_id": "generic", "text": "need", "requirements": []}}
    receiver.receive(original, "requester-z")
    await receiver.start()
    await eventually(lambda: receiver.snapshot()["sessions"])
    await receiver.stop()
    forged = {**original, "message_id": "m-2", "sender_agent_id": "other-z", "type": "APPROVAL", "payload": {"digest": "x"}}
    with pytest.raises(PermissionError, match="pair"):
        receiver.receive(forged, "other-z")
    assert len(receiver.storage.pending_inbox()) == 0


def test_conflicting_request_cannot_claim_pending_session_before_worker_starts(tmp_path):
    receiver = AgentRuntime(config(tmp_path, "provider-z", ["requester-z", "other-z"]), policy=TestPolicy())
    original = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                "payload": {"scenario_id": "generic", "text": "need", "requirements": []}}
    receiver.receive(original, "requester-z")
    with pytest.raises(PermissionError, match="session"):
        receiver.receive({**original, "message_id": "m-2", "sender_agent_id": "other-z"}, "other-z")


@pytest.mark.asyncio
async def test_slow_pair_does_not_block_independent_pair(tmp_path):
    class SlowPolicy(TestPolicy):
        async def decide(self, context):
            if context["peer_id"] == "slow-z":
                await asyncio.sleep(.3)
            return await super().decide(context)

    receiver = AgentRuntime(config(tmp_path, "provider-z", ["slow-z", "fast-z"], facts={"hours": 20}), policy=SlowPolicy())
    for peer in ("slow-z", "fast-z"):
        receiver.receive({"schema_version": 1, "message_id": f"m-{peer}", "request_id": f"r-{peer}", "session_id": f"s-{peer}",
                          "sender_agent_id": peer, "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                          "payload": {"scenario_id": "generic", "text": "need", "requirements": [{"field": "remote", "op": "eq", "value": True}]}}, peer)
    await receiver.start()
    await asyncio.sleep(.12)
    states = {s["peer_id"]: s["state"] for s in receiver.snapshot()["sessions"]}
    await receiver.stop()
    assert "fast-z" in states and "slow-z" not in states


@pytest.mark.asyncio
async def test_initial_hard_fail_filters_without_policy_call(tmp_path):
    class CountingPolicy(TestPolicy):
        def __init__(self):
            self.calls = 0

        async def decide(self, context):
            self.calls += 1
            return await super().decide(context)

    policy = CountingPolicy()
    receiver = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 5}), policy=policy)
    receiver.receive({"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                      "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                      "payload": {"scenario_id": "generic", "text": "need", "requirements": [{"field": "hours", "op": "gte", "value": 18}]}}, "requester-z")
    await receiver.start()
    await eventually(lambda: receiver.snapshot()["sessions"])
    await receiver.stop()
    assert receiver.snapshot()["sessions"][0]["state"] == "NO_MATCH"
    assert policy.calls == 0


@pytest.mark.asyncio
async def test_revised_requirements_do_not_leave_duplicate_owner_questions(tmp_path):
    receiver = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 20}), policy=TestPolicy())
    request = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
               "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
               "payload": {"scenario_id": "generic", "text": "need", "requirements": [{"field": "remote", "op": "eq", "value": True}]}}
    receiver.receive(request, "requester-z")
    await receiver.start()
    await eventually(lambda: receiver.snapshot()["questions"])
    receiver.receive({**request, "message_id": "m-2", "type": "REQUIREMENTS",
                      "payload": {"revision": 2, "requirements": [{"field": "remote", "op": "eq", "value": True}, {"field": "hours", "op": "gte", "value": 18}]}}, "requester-z")
    await eventually(lambda: receiver.snapshot()["sessions"][0].get("requirements_revision") == 2)
    await receiver.stop()
    assert len([q for q in receiver.snapshot()["questions"] if not q["answered"]]) == 1


@pytest.mark.asyncio
async def test_acked_inbox_survives_restart_before_processing(tmp_path):
    first = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 20}), policy=TestPolicy())
    message = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
               "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
               "payload": {"scenario_id": "generic", "text": "need", "requirements": [{"field": "hours", "op": "gte", "value": 18}]}}
    first.receive(message, "requester-z")
    restarted = AgentRuntime(first.config, policy=TestPolicy())
    await restarted.start()
    await eventually(lambda: restarted.snapshot()["sessions"])
    await restarted.stop()
    assert restarted.snapshot()["sessions"][0]["session_id"] == "s-1"
    assert restarted.storage.pending_inbox() == []
    assert len([e for e in restarted.snapshot()["events"] if e["type"] == "REQUEST_RECEIVED"]) == 1


@pytest.mark.asyncio
async def test_approval_requires_live_matching_proposal_and_owner_revision(tmp_path):
    runtime = AgentRuntime(config(tmp_path, "requester-z", ["provider-z"]), policy=TestPolicy())
    session = runtime._new_session("s-1", "r-1", "provider-z", "requester", [])
    session["state"] = "PENDING_APPROVAL"
    session["proposal"] = {"digest": "valid-digest", "version": 1, "terms": {"requirements": [], "provider_facts": {}}}
    runtime.storage.put("session", "s-1", session)
    with pytest.raises(ValueError, match="digest"):
        await runtime.approve("s-1", True, proposal_digest="stale-digest", expected_revision=1)
    with pytest.raises(ValueError, match="revision"):
        await runtime.approve("s-1", True, proposal_digest="valid-digest", expected_revision=2)
    assert runtime.snapshot()["sessions"][0]["approvals"] == []
    await runtime.approve("s-1", True, proposal_digest="valid-digest", expected_revision=1)
    assert runtime.snapshot()["sessions"][0]["artifact"] is None
    with pytest.raises(ValueError, match="already approved"):
        await runtime.approve("s-1", True, proposal_digest="valid-digest")
    with pytest.raises(ValueError, match="already approved"):
        await runtime.approve("s-1", False, proposal_digest="valid-digest")


@pytest.mark.asyncio
async def test_policy_may_reject_passed_provider_after_revised_requirements(tmp_path):
    class RejectPolicy(TestPolicy):
        async def decide(self, context):
            answer = await super().decide(context)
            if context["role"] == "provider" and context["evaluation"]["status"] == "PASS":
                answer["action"] = "REJECT"
                answer["summary"] = "PRIVATE-CANARY-Z declined"
            return answer

    runtime = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 20}), policy=RejectPolicy())
    base = {"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
            "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
            "payload": {"scenario_id": "generic", "text": "need", "requirements": []}}
    runtime.receive(base, "requester-z")
    await runtime.start()
    await eventually(lambda: runtime.snapshot()["sessions"])
    runtime.receive({**base, "message_id": "m-2", "type": "REQUIREMENTS",
                     "payload": {"revision": 2, "requirements": [{"field": "hours", "op": "gte", "value": 18}]}}, "requester-z")
    await eventually(lambda: runtime.snapshot()["sessions"][0]["state"] == "NO_MATCH")
    await runtime.stop()
    assert "REJECT" in [item["type"] for item in runtime.storage.queued_outbox()]
    assert "PRIVATE-CANARY-Z" not in str([item["envelope"] for item in runtime.storage.queued_outbox()])
    assert runtime.storage.pending_inbox() == []


@pytest.mark.asyncio
async def test_policy_error_blocks_inbox_without_automatic_repetition(tmp_path):
    class BrokenPolicy(TestPolicy):
        def __init__(self):
            self.calls = 0

        async def decide(self, context):
            self.calls += 1
            raise ValueError("model returned invalid JSON")

    policy = BrokenPolicy()
    runtime = AgentRuntime(config(tmp_path, "provider-z", ["requester-z"]), policy=policy)
    runtime.receive({"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                     "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                     "payload": {"scenario_id": "generic", "text": "need", "requirements": [{"field": "remote", "op": "eq", "value": True}]}}, "requester-z")
    await runtime.start()
    await eventually(lambda: [e for e in runtime.snapshot()["events"] if e["type"] == "PROCESSING_ERROR"])
    await asyncio.sleep(.15)
    await runtime.stop()
    assert policy.calls == 1
    assert runtime.storage.pending_inbox() == []
    assert runtime.snapshot()["metrics"]["blocked_inbox"] == 1


@pytest.mark.asyncio
async def test_provider_rejects_proposal_with_rewritten_disclosed_facts(tmp_path):
    cfg = config(tmp_path, "provider-z", ["requester-z"], facts={"hours": 20})
    runtime = AgentRuntime(cfg, policy=TestPolicy())
    requirements = [{"field": "hours", "op": "gte", "value": 18}]
    session = runtime._new_session("s-1", "r-1", "requester-z", "provider", requirements)
    runtime.storage.put("session", "s-1", session)
    terms = {"requirements": requirements, "provider_facts": {"hours": 99}}
    runtime.receive({"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                     "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "PROPOSAL", "causation_id": None,
                     "payload": {"digest": proposal_digest("generic", "requester-z", "provider-z", terms), "version": 1, "terms": terms}}, "requester-z")
    await runtime.start()
    await eventually(lambda: runtime.snapshot()["metrics"]["blocked_inbox"] == 1)
    await runtime.stop()
    assert runtime.snapshot()["sessions"][0]["proposal"] is None


@pytest.mark.asyncio
async def test_private_actual_fact_never_appears_in_filter_outbox(tmp_path):
    private_scenario = {"id": "private", "name": "Private", "fields": {"secret_note": {"label": "Note", "type": "string", "aliases": []}},
                        "initial_requirements": [], "result_title": "Result"}
    cfg = config(tmp_path, "provider-z", ["requester-z"], facts={"secret_note": "PRIVATE-OBSERVED"}, scenario=private_scenario)
    cfg["profile"]["public_fields"] = []
    runtime = AgentRuntime(cfg, policy=TestPolicy())
    runtime.receive({"schema_version": 1, "message_id": "m-1", "request_id": "r-1", "session_id": "s-1",
                     "sender_agent_id": "requester-z", "recipient_agent_id": "provider-z", "type": "REQUEST", "causation_id": None,
                     "payload": {"scenario_id": "private", "text": "need", "requirements": [{"field": "secret_note", "op": "eq", "value": "EXPECTED"}]}}, "requester-z")
    await runtime.start()
    await eventually(lambda: runtime.snapshot()["sessions"])
    await runtime.stop()
    assert "PRIVATE-OBSERVED" not in str([row["envelope"] for row in runtime.storage.pending_outbox()])


def test_inbox_blocked_head_prevents_later_same_pair_from_overtaking(tmp_path):
    storage = Storage(str(tmp_path / "queues.sqlite3"))
    def message(message_id, session_id):
        return {"schema_version": 1, "message_id": message_id, "request_id": "r", "session_id": session_id,
                "sender_agent_id": "peer", "recipient_agent_id": "self", "type": "FILTER", "causation_id": None, "payload": {}}
    storage.receive(message("first", "s1"))
    storage.receive(message("second", "s1"))
    storage.receive(message("other", "s2"))
    storage.block("first")
    assert {row["message_id"] for row in storage.pending_inbox()} == {"other"}
    storage.retry_blocked("first")
    assert {row["message_id"] for row in storage.pending_inbox()} == {"first", "other"}
    storage.mark_processed("first")
    assert {row["message_id"] for row in storage.pending_inbox()} == {"second", "other"}


def test_outbox_delayed_head_prevents_later_same_pair_from_overtaking(tmp_path):
    storage = Storage(str(tmp_path / "queues.sqlite3"))
    def message(message_id, session_id):
        return {"schema_version": 1, "message_id": message_id, "request_id": "r", "session_id": session_id,
                "sender_agent_id": "self", "recipient_agent_id": "peer", "type": "FILTER", "causation_id": None, "payload": {}}
    storage.enqueue(message("first", "s1"))
    storage.enqueue(message("second", "s1"))
    storage.enqueue(message("other", "s2"))
    storage.retry("first", 9999999999.0)
    assert {row["message_id"] for row in storage.pending_outbox()} == {"first", "other"}
    storage.delivered("first")
    assert {row["message_id"] for row in storage.pending_outbox()} == {"second", "other"}

@pytest.mark.parametrize('text', ['不确定有没有', '可能有', '不是没有', '需要合伙人有AI产品经验'])
def test_free_text_is_not_guessed_by_boolean_substrings(text):
    from xagent.mvp.scenario import coerce_fact
    with pytest.raises(ValueError):
        coerce_fact('remote', text, SCENARIO)


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [
    {'status':'resolved', 'value':True, 'clarification':None},
    {'status':'clarify', 'value':None, 'clarification':'你是可以远程协作，还是暂时不确定？'},
    {'status':'resolved', 'value':'true', 'clarification':None},
])
@pytest.mark.parametrize('text', ['我可以在家参与远程协作', '是'])
async def test_natural_answer_resumes_only_after_typed_resolution(tmp_path, result, text):
    class AnswerPolicy(TestPolicy):
        async def interpret_answer(self, text, question, scenario):
            assert question['scope'] == 'session' and question['field'] == 'remote'
            assert text in {'我可以在家参与远程协作', '是'}
            return result
    runtime = AgentRuntime(config(tmp_path, 'provider-z', ['requester-z']), policy=AnswerPolicy())
    runtime.receive({'schema_version':1, 'message_id':'m-natural', 'request_id':'r-natural', 'session_id':'s-natural',
        'sender_agent_id':'requester-z', 'recipient_agent_id':'provider-z', 'type':'REQUEST', 'causation_id':None,
        'payload':{'scenario_id':'generic', 'text':'remote', 'requirements':[{'field':'remote','op':'eq','value':True}]}}, 'requester-z')
    await runtime.start()
    try:
        q = (await eventually(lambda: runtime.snapshot()['questions']))[0]
    finally:
        await runtime.stop()
    before = runtime.snapshot()['sessions']
    if type(result['value']) is bool:
        await runtime.answer(q['question_id'], text, remember=True, expected_revision=1)
        assert runtime.snapshot()['memory'] == {'remote':True}
        assert runtime.snapshot()['sessions'][0]['state'] == 'ACTIVE'
        stored = runtime.storage.get('question', q['question_id'])
        assert stored['answer'] == text
        assert stored['interpreted_value'] is True
    else:
        with pytest.raises(ValueError):
            await runtime.answer(q['question_id'], text, remember=True, expected_revision=1)
        assert runtime.snapshot()['memory'] == {}
        assert runtime.snapshot()['sessions'] == before
        assert not runtime.storage.get('question', q['question_id'])['answered']


@pytest.mark.asyncio
@pytest.mark.parametrize('required', [True, False])
async def test_natural_request_answer_changes_requirements_not_owner_memory(tmp_path, required):
    class AnswerPolicy(TestPolicy):
        async def interpret_answer(self, text, question, scenario):
            assert question['scope'] == 'request'
            return {'status':'resolved','value':required,'clarification':None}
    runtime = AgentRuntime(config(tmp_path, 'requester'), policy=AnswerPolicy())
    created = await runtime.broadcast('need hours')
    question = runtime._question({'request_id':created['request_id'], 'session_id':'unused'}, 'remote',
        'request', 'additional_requirements', '远程协作', '是否要求支持远程协作？')
    runtime.storage.put('question', question['question_id'], question)
    await runtime.answer(question['question_id'], '需要支持远程协作' if required else '是否远程都可以', remember=True)
    request = runtime.storage.get('request', created['request_id'])
    expected = [{'field':'hours','op':'gte','value':18}]
    if required:
        expected.append({'field':'remote','op':'eq','value':True})
    assert request['requirements'] == expected
    assert runtime.snapshot()['memory'] == {}
    assert runtime.storage.get('question', question['question_id'])['interpreted_value'] is required


@pytest.mark.asyncio
async def test_uncertain_string_fact_uses_interpreter_before_memory(tmp_path):
    class AnswerPolicy(TestPolicy):
        async def interpret_answer(self, text, question, scenario):
            return {'status':'clarify','value':None,'clarification':'你确认具备哪些技能？'}
    runtime = AgentRuntime(config(tmp_path, 'provider-z', ['requester-z']), policy=AnswerPolicy())
    runtime.receive({'schema_version':1,'message_id':'ms','request_id':'rs','session_id':'ss',
        'sender_agent_id':'requester-z','recipient_agent_id':'provider-z','type':'REQUEST','causation_id':None,
        'payload':{'scenario_id':'generic','text':'skills','requirements':[{'field':'skills','op':'contains','value':'Python'}]}}, 'requester-z')
    await runtime.start()
    try:
        q = (await eventually(lambda: runtime.snapshot()['questions']))[0]
    finally:
        await runtime.stop()
    with pytest.raises(ValueError, match='需要补充'):
        await runtime.answer(q['question_id'], '可能会 Python', remember=True)
    assert runtime.snapshot()['memory'] == {}
    assert runtime.snapshot()['sessions'][0]['state'] == 'WAITING_INPUT'


@pytest.mark.asyncio
async def test_concurrent_answers_remember_each_field_without_overwrite(tmp_path):
    ready = asyncio.Event()
    class ConcurrentPolicy(TestPolicy):
        count = 0
        async def decide(self, context):
            if context['stage'] == 'after_answer':
                self.count += 1
                if self.count == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 2)
            return await super().decide(context)
    runtime = AgentRuntime(config(tmp_path,'provider-z',['requester-z']),policy=ConcurrentPolicy())
    for i, field, value in [(1,'hours',20),(2,'remote',True)]:
        runtime.receive({'schema_version':1,'message_id':f'm{i}','request_id':f'r{i}','session_id':f's{i}',
            'sender_agent_id':'requester-z','recipient_agent_id':'provider-z','type':'REQUEST','causation_id':None,
            'payload':{'scenario_id':'generic','text':'need','requirements':[{'field':field,'op':'eq','value':value}]}}, 'requester-z')
    await runtime.start()
    try:
        await eventually(lambda: len(runtime.snapshot()['questions']) == 2)
    finally:
        await runtime.stop()
    await asyncio.gather(*(runtime.answer(q['question_id'], '20' if q['field']=='hours' else '是', remember=True)
                          for q in runtime.snapshot()['questions']))
    assert runtime.snapshot()['memory'] == {'hours':20,'remote':True}
