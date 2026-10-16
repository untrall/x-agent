"""Exercise the actual subprocess boundary without spending live model quota."""
import asyncio
import json
import os
import sys
import time

import pytest

from xagent.mvp.policy import PolicyError


SCENARIO = {"fields": {"hours": {"type": "number", "label": "每周小时数"}}}


def fake_codex(tmp_path, *, response=None, failure=False, delay=0, events=None):
    path = tmp_path / "codex"
    record = tmp_path / "calls.jsonl"
    path.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
with open({str(record)!r}, 'a') as out:
    out.write(json.dumps({{"args": args, "prompt": prompt, "pid": os.getpid(), "schema": json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())}}) + '\\n')
time.sleep({delay!r})
if {failure!r}:
    print('secret-provider-diagnostic', file=sys.stderr)
    sys.exit(1)
pathlib.Path(args[args.index('--output-last-message')+1]).write_text({json.dumps(response)!r})
for event in {repr(events if events is not None else [{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}])}:
    print(json.dumps(event))
''')
    path.chmod(0o700)
    return str(path), record


def policy(**kwargs):
    from xagent.mvp.codex_policy import CodexPolicy
    return CodexPolicy(**kwargs)


@pytest.mark.asyncio
async def test_cli_extract_uses_light_model_and_isolated_schema_files(tmp_path):
    requirements = [{"field": "hours", "op": "gte", "value": 15}]
    executable, record = fake_codex(tmp_path, response={"requirements": requirements})
    brain = policy(executable=executable)
    async def extract(i):
        result = await brain.extract(f"需求{i} 每周至少15小时", SCENARIO)
        assert brain.last_metadata['model'] == 'gpt-6-luna'
        assert brain.last_metadata['usage']['output_tokens'] == 20
        return result
    results = await asyncio.gather(*(extract(i) for i in range(2)))
    assert results == [requirements, requirements]
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert len(calls) == 2
    assert calls[0]["args"] != calls[1]["args"]  # Separate temp directories / output files.
    for call in calls:
        args = call["args"]
        assert args[args.index('--model') + 1] == 'gpt-6-luna'
        assert 'model_reasoning_effort="low"' in args
        assert '--ephemeral' in args and '--ignore-user-config' in args
        assert args[args.index('--sandbox') + 1] == 'read-only'
        assert '需求' in call['prompt']
        assert call['schema']['additionalProperties'] is False


@pytest.mark.asyncio
async def test_decision_cannot_invent_owner_facts(tmp_path):
    executable, _ = fake_codex(tmp_path, response={
        "action": "PROPOSE", "summary": "通过", "field": None, "question": None,
        "facts": {"hours": 40}, "terms": {},
    })
    with pytest.raises(PolicyError, match="own-source"):
        await policy(executable=executable).decide({"scenario": SCENARIO,
            "allowed_actions": ["PROPOSE"], "evaluation": {"status": "PASS"},
            "own_facts": {"hours": 20}, "public_fields": ["hours"]})


@pytest.mark.asyncio
async def test_provider_gets_fact_question_context_without_requester_followup(tmp_path):
    executable, record = fake_codex(tmp_path, response={
        "action": "ASK_OWNER", "summary": "需补充本人投入", "field": "hours",
        "question": "你每周可以投入多少小时？", "facts": {}, "terms": {},
    })
    scenario = {**SCENARIO, "followup": {"field": "hours", "prompt": "你要求多少小时？"}}
    await policy(executable=executable).decide({"scenario": scenario, "role": "provider",
        "stage": "evaluate", "allowed_actions": ["ASK_OWNER", "REJECT"],
        "evaluation": {"status": "UNKNOWN", "unknown_fields": ["hours"]}})
    sent = json.loads(json.loads(record.read_text())['prompt'].split('INPUT_JSON:\n')[1])
    assert 'followup' not in sent['scenario']
    assert sent['owner_question_kind'] == 'own_fact'
    assert 'followup' in scenario  # Never mutate shared scenario configuration.


@pytest.mark.asyncio
async def test_cli_failure_does_not_fallback_or_expose_stderr(tmp_path):
    executable, record = fake_codex(tmp_path, failure=True)
    with pytest.raises(PolicyError, match="Codex exited") as caught:
        await policy(executable=executable).extract("需求", SCENARIO)
    assert "secret-provider" not in str(caught.value)
    assert len(record.read_text().splitlines()) == 1


@pytest.mark.asyncio
async def test_missing_completion_reports_event_types_without_sensitive_messages(tmp_path):
    executable, _ = fake_codex(tmp_path, response={"requirements": []},
        events=[{"type": "turn.failed", "error": {"message": "private diagnostic"}}])
    with pytest.raises(PolicyError, match="turn.failed") as caught:
        await policy(executable=executable).extract("需求", SCENARIO)
    assert 'private diagnostic' not in str(caught.value)


@pytest.mark.asyncio
async def test_cli_reconnect_events_do_not_discard_a_completed_valid_decision(tmp_path):
    executable, _ = fake_codex(tmp_path, response={"requirements": []}, events=[
        {"type": "turn.started"}, {"type": "error", "message": "Reconnecting"},
        {"type": "turn.completed", "usage": {"output_tokens": 10}},
    ])
    brain = policy(executable=executable)
    assert await brain.extract("需求", SCENARIO) == []
    assert brain.last_metadata['recovered_errors'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_and_cancellation_reap_cli(tmp_path, cancel):
    executable, record = fake_codex(tmp_path, delay=20)
    brain = policy(executable=executable, timeout=2 if cancel else 1)
    task = asyncio.create_task(brain.extract("需求", SCENARIO))
    for _ in range(100):
        if record.exists():
            break
        await asyncio.sleep(.01)
    assert record.exists()
    pid = json.loads(record.read_text().splitlines()[0])['pid']
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else PolicyError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_headless_shutdown_cancels_inflight_owner_model_call(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from scripts.smoke_mvp import Cluster
    executable, record = fake_codex(tmp_path, delay=30)
    group = Cluster(tmp_path, mode="codex", model_env={"XAGENT_CODEX_BIN": executable})
    pid = None
    try:
        group.start(1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(group.call, 1, "POST", "/owner/requests", {"text": "寻找合伙人"})
            try:
                for _ in range(100):
                    if record.exists():
                        break
                    time.sleep(.03)
                pid = json.loads(record.read_text().splitlines()[0])["pid"]
                parent = group.processes[1]
                group.stop(1)
                assert parent.returncode != -9, "App required SIGKILL instead of finishing shutdown"
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                group.close()
            with pytest.raises(Exception):
                pending.result(timeout=3)
    finally:
        group.close()
        if pid is not None:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

@pytest.mark.asyncio
@pytest.mark.parametrize('answer', [
    {'status':'resolved', 'value':True, 'clarification':None},
    {'status':'clarify', 'value':None, 'clarification':'这是必须满足的要求吗？'},
])
async def test_cli_interprets_answer_with_field_type_and_question_scope(tmp_path, answer):
    executable, record = fake_codex(tmp_path, response=answer)
    brain = policy(executable=executable)
    scenario = {'fields':{'experience':{'type':'boolean','label':'AI 产品经验'}}}
    question = {'field':'experience', 'scope':'request','kind':'additional_requirements', 'reason':'是否要求 AI 产品经验？'}
    assert await brain.interpret_answer('需要合伙人有AI产品经验', question, scenario) == answer
    call = json.loads(record.read_text())
    assert call['schema']['properties']['value']['type'] == ['boolean', 'null']
    assert '需要合伙人有AI产品经验' in call['prompt']
    assert 'additional_requirements' in call['prompt']
