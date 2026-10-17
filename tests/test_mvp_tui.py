"""Headless Textual tests for owner scoping and live updates."""
import asyncio

import pytest
from textual.widgets import Button, Input, RichLog, Select

from xagent.mvp.tui import AgentApp


class RuntimeFixture:
    def __init__(self):
        self.config = {"scenario": {"fields": {"hours": {"label": "Weekly hours", "type": "number"}}}}
        self.state = {
            "agent": {"agent_id": "a1", "name": "Agent 1", "port": 8011,
                      "profile": {"facts": {"private": "do not show", "hours": 20}, "public_fields": ["hours"], "tags": ["builder"]}},
            "mode": "deterministic", "requests": [],
            "sessions": [
                {"session_id": "s1", "request_id": "r1", "peer_id": "a2", "state": "PENDING_APPROVAL", "revision": 4,
                 "requirements": [], "terms": {}, "proposal": {"digest": "digest-1", "version": 1, "terms": {}},
                 "approvals": [], "artifact": None, "pending_question_id": None},
                {"session_id": "s2", "request_id": "r1", "peer_id": "a3", "state": "WAITING_INPUT", "revision": 2,
                 "requirements": [], "terms": {}, "proposal": None, "approvals": [], "artifact": None, "pending_question_id": "q2"},
            ],
            "questions": [
                {"question_id": "q1", "session_id": "s1", "request_id": "r1", "field": "hours", "title": "Hours?", "reason": "unknown", "kind": "fact", "revision": 3, "scope": "session", "answered": False},
                {"question_id": "q2", "session_id": "s2", "request_id": "r1", "field": "hours", "title": "How many hours?", "reason": "unknown", "kind": "fact", "revision": 2, "scope": "session", "answered": False},
            ],
            "events": [], "metrics": {}, "memory": {},
        }
        self.calls = []

    def snapshot(self):
        return self.state

    async def broadcast(self, text, requirements=None):
        self.calls.append(("broadcast", text, requirements))
        return {"request_id": "r2", "session_ids": [], "snapshot": self.state}

    async def answer(self, question_id, text, remember=False, expected_revision=None):
        self.calls.append(("answer", question_id, text, remember, expected_revision))
        return self.state

    async def approve(self, session_id, approve, proposal_digest=None, expected_revision=None):
        self.calls.append(("approve", session_id, approve, proposal_digest, expected_revision))
        return self.state

    def retry_blocked_message(self, message_id):
        self.calls.append(("retry", message_id))
        return self.state


@pytest.mark.asyncio
async def test_identity_displays_actual_configured_brain():
    runtime = RuntimeFixture()
    runtime.state.update(mode="codex", brain={"model": "gpt-6-luna", "reasoning": "low"})
    app = AgentApp(runtime)
    async with app.run_test():
        assert 'gpt-6-luna' not in str(app.query_one('#identity').content)
        app.action_toggle_debug()
        identity = str(app.query_one("#identity").content)
        assert "gpt-6-luna" in identity
        assert "low" in identity


@pytest.mark.asyncio
async def test_bare_reply_targets_selected_question_not_other_session():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        app.query_one("#question-select", Select).value = "q2"
        field = app.query_one("#owner-input", Input)
        field.value = "yes"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("answer", "q2", "yes", False, 2)]
        assert "private" not in str(app.query_one("#profile").content)


@pytest.mark.asyncio
async def test_natural_text_never_approves_and_command_binds_displayed_digest():
    runtime = RuntimeFixture()
    runtime.state["questions"] = []
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        app.action_new_request()
        field = app.query_one("#owner-input", Input)
        field.value = "I approve"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("broadcast", "I approve", None)]
        app.action_commands()
        field.value = "/approve s1"
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls[-1] == ("approve", "s1", True, "digest-1", 4)


@pytest.mark.asyncio
async def test_new_event_updates_while_draft_input_stays_intact():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        field = app.query_one("#owner-input", Input)
        field.value = "unfinished draft"
        runtime.state["events"].append({"seq": 1, "timestamp": "now", "type": "PEER_MESSAGE", "session_id": "s1", "peer_id": "a2", "summary": "Arrived while typing", "payload": {}})
        await asyncio.sleep(0.35)
        await pilot.pause()
        assert field.value == "unfinished draft"
        assert app.focused is field
        log = app.query_one("#events", RichLog)
        assert any("Arrived while typing" in str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_new_question_does_not_capture_request_already_being_typed():
    runtime = RuntimeFixture()
    runtime.state["questions"] = []
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        app.action_new_request()
        field = app.query_one("#owner-input", Input)
        field.value = "Need a venue for 30 people"
        field.focus()
        runtime.state["questions"].append({"question_id": "new-q", "session_id": "s2", "request_id": "r1",
                                            "field": "hours", "title": "Hours?", "reason": "unknown",
                                            "kind": "fact", "revision": 1, "scope": "session", "answered": False})
        await asyncio.sleep(0.35)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("broadcast", "Need a venue for 30 people", None)]


@pytest.mark.asyncio
async def test_remember_command_persists_stable_answer_and_profile_shows_public_memory():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        field = app.query_one("#owner-input", Input)
        field.value = "/remember q2 30"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("answer", "q2", "30", True, 2)]
        runtime.state["memory"] = {"hours": 30, "private": "still hidden"}
        app.refresh_from_runtime()
        profile = str(app.query_one("#profile").content)
        assert "hours: 30" in profile
        assert "still hidden" not in profile


@pytest.mark.asyncio
async def test_approve_without_id_uses_selected_session_proposal():
    runtime = RuntimeFixture()
    runtime.state["questions"] = []
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        app.action_commands()
        field = app.query_one("#owner-input", Input)
        field.value = "/approve"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("approve", "s1", True, "digest-1", 4)]


@pytest.mark.asyncio
async def test_event_log_explains_public_requirements_and_filter_reasons():
    runtime = RuntimeFixture()
    runtime.state["events"] = [
        {"seq": 1, "timestamp": "now", "type": "REQUEST_RECEIVED", "session_id": "s1", "peer_id": "a2",
         "summary": "Peer request received", "payload": {"requirements": [{"field": "hours", "op": "gte", "value": 20}]}},
        {"seq": 2, "timestamp": "now", "type": "FILTER_RESULT", "session_id": "s1", "peer_id": "a2",
         "summary": "Local filter PASS", "payload": {"status": "PASS", "reasons": [
             {"field": "hours", "status": "PASS", "reason": "hours gte 20: matched"}]}}
    ]
    app = AgentApp(runtime)
    async with app.run_test():
        log = app.query_one("#events", RichLog)
        rendered = " ".join(str(line) for line in log.lines)
        assert "Weekly hours" in rendered
        assert "20" in rendered
        assert "符合" in rendered


@pytest.mark.asyncio
async def test_processing_error_shows_message_id_and_retries_only_on_command():
    runtime = RuntimeFixture()
    runtime.state["events"] = [{"seq": 1, "timestamp": "now", "type": "PROCESSING_ERROR",
                                "session_id": "s1", "peer_id": "a2", "summary": "model timeout",
                                "payload": {"message_id": "m-blocked", "blocked": True}}]
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        log = app.query_one("#events", RichLog)
        rendered = " ".join(str(line) for line in log.lines)
        assert "model timeout" in rendered
        assert "m-blocked" in rendered
        assert runtime.calls == []
        field = app.query_one("#owner-input", Input)
        field.value = "/retry m-blocked"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.calls == [("retry", "m-blocked")]


@pytest.mark.asyncio
async def test_loop_in_only_appears_for_question_then_closes_when_answered():
    runtime = RuntimeFixture()
    runtime.state['sessions'] = []
    runtime.state['questions'] = []
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        panel = app.query_one('#owner-panel')
        assert not panel.display
        assert not app.query_one('#details').display
        runtime.state['questions'] = [{"question_id": "q", "title": "每周投入？", "reason": "你每周能投入多少小时？",
            "field": "hours", "scope": "request", "request_id": "r", "revision": 1, "answered": False}]
        app.refresh_from_runtime()
        await pilot.pause()
        assert panel.display
        assert '需要你参与' in str(app.query_one('#loop-title').content)
        assert app.focused is app.query_one('#owner-input')
        app._pulse_loop_in()
        first = panel.has_class('pulse')
        app._pulse_loop_in()
        assert panel.has_class('pulse') != first
        runtime.state['questions'][0]['answered'] = True
        app.refresh_from_runtime()
        await pilot.pause()
        assert not panel.display
        assert not panel.has_class('pulse')


@pytest.mark.asyncio
async def test_approval_card_targets_pending_peer_and_hides_after_own_approval():
    runtime = RuntimeFixture()
    runtime.state['questions'] = []
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)) as pilot:
        app.query_one('#session-select', Select).value = 's2'
        await pilot.pause()
        assert app.query_one('#owner-panel').display
        assert not app.query_one('#owner-input').display
        assert 'a2' in str(app.query_one('#question-detail').content)
        await pilot.click('#approve-button')
        await pilot.pause()
        assert runtime.calls == [('approve', 's1', True, 'digest-1', 4)]
        runtime.state['sessions'][0]['approvals'] = ['a1']
        app.refresh_from_runtime()
        await pilot.pause()
        assert not app.query_one('#owner-panel').display


@pytest.mark.asyncio
async def test_explicit_new_request_is_not_routed_to_an_existing_question():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press('ctrl+n')
        field = app.query_one('#owner-input', Input)
        field.value = '寻找另一位合伙人'
        await pilot.press('enter')
        await pilot.pause()
        assert runtime.calls == [('broadcast', '寻找另一位合伙人', None)]


@pytest.mark.asyncio
async def test_agent_stream_has_direction_and_distinguishes_local_decisions():
    runtime = RuntimeFixture()
    runtime.state['events'] = [
        {'seq': 1, 'type': 'REQUEST_RECEIVED', 'peer_id': 'a2', 'summary': 'Peer request received',
         'payload': {'requirements': [{'field': 'hours', 'op': 'gte', 'value': 20}]}},
        {'seq': 2, 'type': 'POLICY_DECISION', 'peer_id': 'a2', 'summary': '已知条件满足，可以提出试合作。',
         'payload': {'action': 'PROPOSE'}},
    ]
    app = AgentApp(runtime)
    async with app.run_test():
        rendered = ' '.join(str(line) for line in app.query_one('#events', RichLog).lines)
        assert 'a2 → 我' in rendered
        assert '我的 Agent · 决策' in rendered
        assert '已知条件满足' in rendered


@pytest.mark.asyncio
async def test_command_shortcut_opens_our_composer():
    app = AgentApp(RuntimeFixture())
    async with app.run_test() as pilot:
        await pilot.press('ctrl+p')
        await pilot.pause()
        assert app.query_one('#owner-panel').display
        assert app._composer == 'commands'
        assert app.focused is app.query_one('#owner-input')


@pytest.mark.asyncio
async def test_question_draft_keeps_display_and_submission_on_same_question():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        select = app.query_one('#question-select', Select)
        select.value = 'q1'
        field = app.query_one('#owner-input', Input)
        field.value = '20'
        await pilot.pause()
        select.value = 'q2'
        await pilot.pause()
        assert select.value == 'q1'
        assert 'a2' in str(app.query_one('#question-detail').content)
        field.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert runtime.calls == [('answer', 'q1', '20', False, 3)]


@pytest.mark.asyncio
async def test_failed_answer_restores_draft_and_keyboard_focus():
    runtime = RuntimeFixture()
    async def fail(*args, **kwargs):
        raise ValueError('请输入数字')
    runtime.answer = fail
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        field = app.query_one('#owner-input', Input)
        field.value = '不知道'
        await pilot.press('enter')
        await pilot.pause()
        assert field.value == '不知道'
        assert app.focused is field


@pytest.mark.asyncio
async def test_retired_question_draft_can_be_cleared_without_becoming_new_request():
    runtime = RuntimeFixture()
    runtime.state['sessions'] = []
    runtime.state['questions'] = runtime.state['questions'][:1]
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        field = app.query_one('#owner-input', Input)
        field.value = '20'
        await pilot.pause()
        runtime.state['questions'][0]['answered'] = True
        app.refresh_from_runtime()
        await pilot.pause()
        assert app.query_one('#owner-panel').display
        assert '已更新' in str(app.query_one('#loop-title').content)
        assert field.display
        field.value = ''
        await pilot.pause()
        assert not app.query_one('#owner-panel').display
        assert runtime.calls == []


@pytest.mark.asyncio
async def test_fact_question_has_no_buttons_and_enter_submits():
    runtime = RuntimeFixture()
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)) as pilot:
        assert not app.query_one('#owner-actions').display
        field = app.query_one('#owner-input', Input)
        field.value = '每周二十小时'
        field.focus()
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert runtime.calls == [('answer', 'q1', '每周二十小时', False, 3)]


@pytest.mark.asyncio
async def test_profile_card_and_conversation_are_the_only_idle_content():
    runtime = RuntimeFixture()
    runtime.state['questions'] = []
    for session in runtime.state['sessions']:
        session.update(state='ACTIVE',proposal=None)
    runtime.state['agent']['profile']['description'] = '产品合伙人，关注早期创业。'
    runtime.state['agent']['profile']['public_fields'].append('remote')
    runtime.config['scenario']['fields']['remote'] = {'type':'boolean','label':'远程协作'}
    app = AgentApp(runtime)
    async with app.run_test() as pilot:
        assert app.query_one('#profile-card').display
        profile = str(app.query_one('#profile').content)
        assert '产品合伙人' in profile
        assert '20' in profile and '远程协作：待确认' in profile
        assert 'do not show' not in profile
        assert not app.query_one('#toolbar').display
        assert not app.query_one('#selectors').display
        assert not app.query_one('#owner-panel').display
        await pilot.press('ctrl+n')
        await pilot.pause()
        assert app.query_one('#owner-panel').display


@pytest.mark.asyncio
async def test_profile_card_updates_from_memory_and_hides_machine_ids():
    runtime = RuntimeFixture()
    runtime.state['memory'] = {'hours':35, 'private':'secret'}
    app = AgentApp(runtime)
    async with app.run_test():
        text = str(app.query_one('#profile').content)
        assert '35' in text and '20' not in text
        assert 'secret' not in text
        assert all('q1' not in label and 's1' not in label for label, _ in app._question_options)


def _yes_no_runtime():
    runtime = RuntimeFixture()
    runtime.state['sessions'] = []
    runtime.state['questions'] = [{"question_id": "q", "title": "AI 产品经验", "reason": "是否要求 AI 产品经验？",
        "field": "hours", "scope": "request", "request_id": "r", "revision": 1, "answered": False,
        "kind": "additional_requirements", "options": ["是", "否"]}]
    return runtime


@pytest.mark.asyncio
async def test_question_has_no_quick_buttons():
    runtime = _yes_no_runtime()
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)):
        assert not list(app.query('#yes-button, #no-button, #remember-button'))
        assert not app.query_one('#owner-actions').display
        assert app.query_one('#owner-input').display


@pytest.mark.asyncio
async def test_rejected_answer_shows_inline_error_in_loop_card():
    runtime = _yes_no_runtime()

    async def reject(question_id, text, remember=False, expected_revision=None):
        raise ValueError("hours answer must be yes/no")
    runtime.answer = reject
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)) as pilot:
        field = app.query_one('#owner-input', Input)
        field.value = "嗯"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        error = app.query_one('#loop-error')
        assert error.display
        assert '请补充说明' in str(error.content)
        assert field.value == "嗯"
        field.value = "是"
        await pilot.pause()
        assert not app.query_one('#loop-error').display


@pytest.mark.asyncio
async def test_natural_answer_enter_submits_without_send_button():
    runtime = _yes_no_runtime()
    runtime.state['questions'][0]['reason'] += '请回答是或否。'
    app = AgentApp(runtime)
    async with app.run_test(size=(100, 35)) as pilot:
        assert not list(app.query('#send-button'))
        assert '回答是或否' not in str(app.query_one('#question-detail').content)
        field = app.query_one('#owner-input', Input)
        field.value = '需要合伙人有AI产品经验'
        field.focus()
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert runtime.calls == [('answer','q','需要合伙人有AI产品经验',False,1)]


@pytest.mark.asyncio
async def test_clarification_restores_original_words_for_retry():
    runtime = RuntimeFixture()
    async def unclear(*args, **kwargs):
        raise ValueError('需要补充：每周能明确投入多少小时？')
    runtime.answer = unclear
    app = AgentApp(runtime)
    async with app.run_test(size=(100,35)) as pilot:
        field = app.query_one('#owner-input', Input)
        field.value = '可能二十小时'
        await pilot.pause()
        field.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert field.value == '可能二十小时'
        assert '需要补充' in str(app.query_one('#loop-error').content)
        assert app._draft_question_id == 'q1'


def _choice_runtime():
    runtime = RuntimeFixture()
    runtime.config["peers"] = [{"agent_id": f"a{n}", "name": name}
                               for n, name in ((2, "林小满"), (3, "陈语桐"), (4, "方糖"))]
    runtime.state["questions"] = []
    runtime.state["sessions"] = [
        {"session_id": f"s{n}", "request_id": "r1", "peer_id": f"a{n}", "role": "requester",
         "state": "PENDING_APPROVAL", "revision": 3, "requirements": [], "terms": {},
         "proposal": {"digest": f"d{n}", "version": 1, "terms": {}}, "approvals": [],
         "artifact": None, "pending_question_id": None}
        for n in (2, 3, 4)]

    async def chat(session_id, text):
        runtime.calls.append(("chat", session_id, text))
        return runtime.state

    async def choose(session_id):
        runtime.calls.append(("choose", session_id))
        return runtime.state
    runtime.chat, runtime.choose = chat, choose
    return runtime


async def _send(pilot, app, line):
    field = app.query_one('#owner-input', Input)
    await pilot.pause()
    assert app.focused is field, f'focus lost before: {line}'
    field.value = line
    await pilot.press('enter')
    await pilot.pause(0.3)


@pytest.mark.asyncio
async def test_dropdown_target_receives_plain_text_and_shortcuts_switch_it():
    runtime = _choice_runtime()
    app = AgentApp(runtime)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        assert '3 选 1' in str(app.query_one('#loop-title').content)
        assert app.query_one('#choice-bar').display and app.query_one('#chat-target', Select).value == 's2'
        await _send(pilot, app, '周末怎么过？')            # default target: first candidate
        await _send(pilot, app, '那平时呢？')              # same person again
        await pilot.press('ctrl+down')
        await pilot.pause()
        assert app.query_one('#chat-target', Select).value == 's3'
        await _send(pilot, app, '喜欢户外吗？')
        assert runtime.calls == [("chat", "s2", "周末怎么过？"), ("chat", "s2", "那平时呢？"),
                                 ("chat", "s3", "喜欢户外吗？")]
        assert str(app.query_one('#choose-button', Button).label) == '选定 陈语桐'
        await pilot.click('#choose-button')
        await pilot.pause(0.3)
        assert runtime.calls[-1] == ("choose", "s3")
        assert not any(c[0] == "broadcast" for c in runtime.calls)


@pytest.mark.asyncio
async def test_at_name_tolerates_one_wrong_character_number_and_keeps_text_on_error():
    runtime = _choice_runtime()
    app = AgentApp(runtime)
    async with app.run_test(size=(120, 45)) as pilot:
        await _send(pilot, app, '@陈雨桐 周末怎么过？')      # IME homophone for 陈语桐
        await _send(pilot, app, '@3 你好')                  # numbered: 3rd = 方糖
        assert runtime.calls == [("chat", "s3", "周末怎么过？"), ("chat", "s4", "你好")]
        await _send(pilot, app, '@王五 在吗')
        assert app.query_one('#owner-input', Input).value == '@王五 在吗'
        assert '没有待确认的候选「王五」' in str(app.query_one('#loop-error').content)


@pytest.mark.asyncio
async def test_choice_panel_shows_latest_chat_of_current_target_only():
    runtime = _choice_runtime()
    runtime.state["events"] = [
        {"seq": 1, "type": "CHAT_SENT", "session_id": "s3", "peer_id": "a3", "summary": "周末怎么过？", "payload": {"chat_id": "c1"}},
    ]
    app = AgentApp(runtime)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        assert "周末怎么过" not in str(app.query_one('#question-detail').content)   # target is 林小满
        await pilot.press('ctrl+down')
        await pilot.pause()
        detail = str(app.query_one('#question-detail').content)
        assert "你 → 陈语桐：周末怎么过？" in detail and "正在回答" in detail
        assert not app.query_one('#selectors').display
        runtime.state["events"].append({"seq": 2, "type": "CHAT_REPLY", "session_id": "s3", "peer_id": "a3",
                                        "summary": "喜欢露营和跑步。", "payload": {"chat_id": "c1", "ok": True}})
        await pilot.pause(0.4)
        assert "陈语桐 的 Agent：喜欢露营和跑步。" in str(app.query_one('#question-detail').content)


@pytest.mark.asyncio
async def test_after_choosing_owner_waits_and_cannot_rechoose():
    runtime = _choice_runtime()
    runtime.state["sessions"][1]["approvals"] = ["a1"]        # chose 陈语桐, waiting
    app = AgentApp(runtime)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        assert '已选定 陈语桐' in str(app.query_one('#loop-title').content)
        assert not app.query_one('#owner-input').display and not app.query_one('#choice-bar').display
        assert not app.query_one('#approve-button').display


@pytest.mark.asyncio
async def test_candidate_is_asked_only_after_being_chosen():
    runtime = RuntimeFixture()
    runtime.state["questions"] = []
    runtime.state["sessions"] = [
        {"session_id": "p1", "request_id": "r1", "peer_id": "a2", "role": "provider", "state": "PENDING_APPROVAL",
         "revision": 2, "requirements": [], "terms": {}, "proposal": {"digest": "dp", "version": 1, "terms": {}},
         "approvals": [], "artifact": None, "pending_question_id": None}]
    runtime.config["peers"] = [{"agent_id": "a2", "name": "阿哲"}]
    app = AgentApp(runtime)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        assert not app.query_one('#owner-panel').display
        assert '等待对方选择' in str(app.query_one('#phase').content)
        runtime.state["sessions"][0]["approvals"] = ["a2"]    # 阿哲 chose me
        await pilot.pause(0.4)
        assert '阿哲 选择了你 · 是否接受？' in str(app.query_one('#loop-title').content)
        assert str(app.query_one('#approve-button', Button).label) == '接受'
        assert str(app.query_one('#reject-button', Button).label) == '婉拒'
        await pilot.click('#approve-button')
        await pilot.pause(0.3)
        assert runtime.calls == [("approve", "p1", True, "dp", 2)]
