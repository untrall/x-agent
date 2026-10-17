"""One-owner Textual view over an already running AgentRuntime."""
from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, RichLog, Select, Static
from . import pixel
from .profile import profile_view


class AgentApp(App):
    """Display local public state and route owner actions to this runtime only."""

    BINDINGS = [Binding("ctrl+n", "new_request", "发起需求", priority=True),
                Binding("ctrl+p", "commands", "命令", priority=True),
                Binding("ctrl+d", "toggle_debug", "详情", priority=True),
                Binding("ctrl+up", "chat_target(-1)", "上一位候选", priority=True),
                Binding("ctrl+down", "chat_target(1)", "下一位候选", priority=True),
                ("escape", "close_composer", "返回交流")]

    CSS = """
    Screen { layout: vertical; background: $background; }
    #profile-card { height: auto; max-height: 9; border: tall $primary; margin: 0 1; padding: 0 1; background: $surface; }
    #profile-card { border-title-color: $primary; border-title-style: bold; }
    #avatar { width: 20; height: 7; padding: 0 2 0 0; }
    /* Very short windows: drop the pet so the decision panel still fits. */
    Screen.compact #avatar { display: none; }
    #profile-text { height: auto; width: 1fr; }
    #identity { height: auto; text-style: bold; color: $primary; }
    #profile { height: auto; max-height: 4; color: $text-muted; overflow-y: auto; }
    #toolbar { height: 3; padding: 0 1; }
    #toolbar Button { min-width: 10; width: auto; margin-right: 1; }
    #phase { height: 1; padding: 0 1; color: $secondary; text-style: bold; }
    #selectors { height: 3; }
    #session-select, #question-select { width: 1fr; margin: 0 1; }
    #body { height: 1fr; }
    #events { width: 2fr; height: 1fr; border: tall $primary 60%; margin: 0 1; background: $background; }
    #events { border-title-color: $primary; border-title-style: bold; }
    #details { width: 1fr; min-width: 20; height: 1fr; border: tall $secondary; margin: 0 1; padding: 0 1; overflow-y: auto; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #owner-panel { height: auto; max-height: 60%; border: thick $warning; margin: 0 1; padding: 0 1; background: $surface; }
    #owner-panel.pulse { border: thick $primary; background: $warning 8%; }
    Button { border: none; height: 3; text-style: bold; }
    Button.-success { background: $primary; color: $background; }
    Button.-error { background: $panel; color: $text; }
    #loop-title { height: 1; text-style: bold; color: $warning; }
    #loop-error { height: auto; color: $error; text-style: bold; }
    #question-detail { height: auto; max-height: 8; overflow-y: auto; }
    #question-select { width: 1fr; margin: 0; }
    #owner-input { height: 3; }
    #owner-actions { height: 3; }
    #owner-actions Button { min-width: 14; width: auto; margin-right: 1; }
    #choice-bar { height: 3; }
    #chat-label { width: auto; padding: 1 1 0 0; }
    #chat-target { width: 1fr; margin: 0; }
    """

    def __init__(self, runtime: Any):
        super().__init__()
        self.runtime = runtime
        self._snapshot: dict = {}
        self._last_event_seq = 0
        self._session_options: list[tuple[str, str]] = []
        self._question_options: list[tuple[str, str]] = []
        self._draft_active = False
        self._draft_question_id: str | None = None
        self._chat_target: str | None = None  # session_id picked in the choice dropdown
        self._chat_options: list[tuple[str, str]] = []
        self._composer: str | None = None
        self._busy = False
        self._loop_key = None
        self._loop_session_id: str | None = None
        self._needs_owner = False
        self._debug = False
        self._loop_error = ''
        self._loop_question_id: str | None = None
        self._failed_text = ''
        self._error_question_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="profile-card"):
            yield Static("", id="avatar", markup=False)
            with Vertical(id="profile-text"):
                yield Static("Agent", id="identity", markup=False)
                yield Static("", id="profile", markup=False)
        with Horizontal(id="toolbar"):
            yield Button("＋ 发起需求", id="new-request")
            yield Button("命令", id="commands")
        yield Static("Agent 待命", id="phase", markup=False)
        with Horizontal(id="selectors"):
            yield Select([], prompt="Session", id="session-select")
        with Horizontal(id="body"):
            yield RichLog(id="events", markup=False, wrap=True, highlight=False, max_lines=1000)
            with Vertical(id="details"):
                yield Static("", id="session-detail", markup=False)
        with Vertical(id="owner-panel"):
            yield Static("", id="loop-title", markup=False)
            yield Select([], prompt="选择待答问题", id="question-select")
            with Horizontal(id="choice-bar"):
                yield Static("正在和：", id="chat-label", markup=False)
                yield Select([], prompt="选择聊天对象", id="chat-target")
            yield Static("", id="question-detail", markup=False)
            yield Static("", id="loop-error", markup=False)
            yield Input(placeholder="输入我的回答，Enter 交还 Agent", id="owner-input")
            with Horizontal(id="owner-actions"):
                yield Button("选定", id="choose-button", variant="success")
                yield Button("批准方案", id="approve-button", variant="success")
                yield Button("拒绝方案", id="reject-button", variant="error")
                yield Button("返回交流", id="close-composer")
        yield Static("Ctrl+N 发起需求 · Ctrl+D 详情 · Ctrl+Q 退出", id="status", markup=False)

    def on_mount(self) -> None:
        self.register_theme(pixel.THEME)
        self.theme = pixel.THEME.name
        self._spin = 0
        self._phase_text = ''
        self._phase_spinning = False
        self.refresh_from_runtime()
        self.set_interval(0.25, self.refresh_from_runtime)
        self.set_interval(0.75, self._pulse_loop_in)
        self.set_interval(0.12, self._tick_spinner)
        self.query_one("#events", RichLog).border_title = "AGENTS 先聊 · 实时交流"
        self.query_one('#profile-card').border_title = '▚ X-AGENT · 我的 Agent'

    def _tick_spinner(self) -> None:
        """Claude-Code-style ✻ glyph cycling in front of the phase text while working."""
        if not self._phase_spinning:
            return
        self._spin = (self._spin + 1) % len(pixel.SPINNER)
        self._show_phase()

    def _show_phase(self) -> None:
        glyph = pixel.SPINNER[self._spin] if self._phase_spinning else ''
        try:
            self.query_one('#phase', Static).update(f"{glyph} {self._phase_text}" if glyph else self._phase_text)
        except NoMatches:
            pass

    def refresh_from_runtime(self) -> None:
        """A short local snapshot read; the timer never waits on peer I/O."""
        try:
            state = self.runtime.snapshot()
            if not isinstance(state, dict):
                raise ValueError("snapshot must be an object")
            self._snapshot = state
            self._render_state()
        except Exception as exc:
            self._set_status(f"State error: {exc}")

    def _render_state(self) -> None:
        agent = self._snapshot.get("agent") or {}
        profile = agent.get("profile") or {}
        brain = self._snapshot.get("brain") or {}
        brain_label = " · ".join(str(brain[key]) for key in ("model", "reasoning") if brain.get(key))
        identity = (
            f"{agent.get('name', 'Agent')} · {agent.get('agent_id', '?')} · port {agent.get('port', '?')} · {self._snapshot.get('mode', '?')}"
            + (f" · {brain_label}" if brain_label else "")
        )
        self.query_one('#identity', Static).update(identity if self._debug else str(agent.get('name') or '我的 Agent'))
        self.screen.set_class(self.size.height < 20, 'compact')
        self.query_one('#avatar', Static).update(pixel.avatar(agent.get('agent_id')))
        facts = {**(profile.get("facts") or {}), **(self._snapshot.get("memory") or {})}
        scenario = (getattr(self.runtime, 'config', {}) or {}).get('scenario') or {}
        self.query_one('#profile', Static).update(profile_view(profile, scenario, facts)['summary'])
        self.query_one('#toolbar').display = self._debug

        sessions = self._snapshot.get("sessions") or []
        session_select = self.query_one("#session-select", Select)
        selected_session = session_select.value
        session_options = [
            (escape(f"{i + 1}. {self._peer_name(s.get('peer_id'))} · " +
                    (f"{s.get('state')} · {str(s.get('session_id'))[:8]}" if self._debug else
                     # NO_MATCH after a proposal means the other owner declined it.
                     ('对方已婉拒' if s.get('state') == 'NO_MATCH' and s.get('proposal') else
                      {'PENDING_APPROVAL':'待确认方案', 'CONNECTED':'已达成合作', 'NO_MATCH':'不匹配',
                       'REJECTED':'已婉拒', 'WAITING_INPUT':'等待补充', 'ACTIVE':'交流中', 'PROPOSED':'已提出方案'}.get(s.get('state'), '交流中')))), str(s['session_id']))
            for i, s in enumerate(sessions) if s.get('session_id')
        ]
        if session_options != self._session_options:
            session_select.set_options(session_options)
            self._session_options = session_options
        session_ids = {value for _, value in session_options}
        if selected_session in session_ids and session_select.value != selected_session:
            session_select.value = selected_session
        elif selected_session not in session_ids and session_options:
            session_select.value = session_options[0][1]

        questions = [q for q in self._snapshot.get("questions") or [] if not q.get("answered")]
        question_select = self.query_one("#question-select", Select)
        selected_question = question_select.value
        question_options = [
            (escape(f"{i + 1}. {str(q.get('title') or q.get('field') or '待答问题')} · " +
                    (self._peer_name(next((s.get('peer_id') for s in sessions if s.get('session_id') == q.get('session_id')), None))
                     if q.get('scope') == 'session' else '本次需求')), str(q['question_id']))
            for i, q in enumerate(questions) if q.get('question_id')
        ]
        if question_options != self._question_options:
            question_select.set_options(question_options)
            self._question_options = question_options
        question_ids = {value for _, value in question_options}
        if selected_question in question_ids and question_select.value != selected_question:
            question_select.value = selected_question
        elif selected_question not in question_ids and question_options and not self._draft_active:
            question_select.value = question_options[0][1]
        actionable = [s for s in sessions if s.get('state') == 'PENDING_APPROVAL' and agent.get('agent_id') not in s.get('approvals', [])]
        results = [s for s in sessions if s.get('artifact')]
        # The choice panel names candidates itself; the dropdown would only eat rows.
        choosing = bool(self._choice_sessions() or self._awaiting_session())
        self.query_one('#selectors').display = bool((self._debug and sessions) or (len(actionable) > 1 and not choosing) or len(results) > 1)
        self._render_details()

        log = self.query_one("#events", RichLog)
        for event in sorted(self._snapshot.get("events") or [], key=lambda x: int(x.get("seq") or 0)):
            seq = int(event.get("seq") or 0)
            if seq <= self._last_event_seq:
                continue
            speaker, target, text = self._conversation_parts(event)
            peer = self._peer_name(event.get('peer_id'))
            log.write(pixel.role_line(
                (speaker, self._role_label(speaker, peer)),
                (target, self._role_label(target, peer)) if target else None, text))
            self._last_event_seq = seq

    def _awaiting_session(self) -> dict | None:
        """The requester pair I chose, still waiting for the other owner."""
        own_id = (self._snapshot.get('agent') or {}).get('agent_id')
        return next((s for s in self._snapshot.get('sessions') or []
                     if s.get('role') == 'requester' and s.get('state') == 'PENDING_APPROVAL'
                     and own_id in s.get('approvals', [])), None)

    def _choice_sessions(self) -> list[dict]:
        """Requester sessions whose proposals wait on my choice (none while one awaits)."""
        if self._awaiting_session():
            return []
        own_id = (self._snapshot.get('agent') or {}).get('agent_id')
        return [s for s in self._snapshot.get('sessions') or []
                if s.get('role') == 'requester' and s.get('state') == 'PENDING_APPROVAL'
                and s.get('proposal') and own_id not in s.get('approvals', [])]

    def _sync_chat_target(self, choices: list[dict]) -> None:
        options = [(self._peer_name(s.get('peer_id')), s['session_id']) for s in choices]
        select = self.query_one('#chat-target', Select)
        if options != self._chat_options:
            select.set_options(options)
            self._chat_options = options
        ids = [value for _, value in options]
        if self._chat_target not in ids:
            self._chat_target = ids[0] if ids else None
        if self._chat_target and select.value != self._chat_target:
            select.value = self._chat_target

    def action_chat_target(self, step: int) -> None:
        ids = [value for _, value in self._chat_options]
        if not ids:
            return
        index = ids.index(self._chat_target) if self._chat_target in ids else 0
        self._chat_target = ids[(index + step) % len(ids)]
        self._render_loop_in()

    def _latest_chat(self, session_ids: set) -> str:
        """Last question and its reply, shown in the choice panel itself so it
        stays visible even when the conversation log is squeezed."""
        events = [e for e in self._snapshot.get('events') or []
                  if e.get('session_id') in session_ids and e.get('type') in {'CHAT_SENT', 'CHAT_REPLY'}]
        sent = next((e for e in reversed(events) if e['type'] == 'CHAT_SENT'), None)
        if sent is None:
            return ''
        peer = self._peer_name(sent.get('peer_id'))
        chat_id = (sent.get('payload') or {}).get('chat_id')
        reply = next((e for e in events if e['type'] == 'CHAT_REPLY'
                      and (e.get('payload') or {}).get('chat_id') == chat_id), None)
        answer = reply['summary'] if reply else f'（{peer}的 Agent 正在回答…）'
        return f"我 → {peer}的 Agent：{sent.get('summary')}\n{peer}的 Agent → 我：{answer}"

    def _choice_by_name(self, name: str) -> dict:
        """Exact name, list number (1-based), unique prefix, or a unique name
        off by one character (an IME homophone such as 陈雨桐 for 陈语桐)."""
        choices = self._choice_sessions()
        named = [(self._peer_name(s.get('peer_id')), s) for s in choices]
        tests = (
            lambda n: n == name,
            lambda n: name.isdigit() and named[int(name) - 1][0] == n if name.isdigit() and 0 < int(name) <= len(named) else False,
            lambda n: bool(name) and n.startswith(name),
            lambda n: len(n) == len(name) and sum(a != b for a, b in zip(n, name)) == 1,
        )
        for test in tests:
            hits = [s for n, s in named if test(n)]
            if len(hits) == 1:
                return hits[0]
        names = '、'.join(n for n, _ in named) or '无'
        raise ValueError(f'需要补充：没有待确认的候选「{name}」，可选：{names}')

    def _peer_name(self, peer_id) -> str:
        peers = (getattr(self.runtime, 'config', {}) or {}).get('peers', [])
        peer = next((p for p in peers if p.get('agent_id') == peer_id), {})
        return str(peer.get('name') or peer_id or '对方')

    # Four roles in every window, always named the same way:
    #   我 (this window's owner) · 我的 Agent · X本人 · X的 Agent
    # plus the agent's own internal checks, shown dimmed.
    ME, MY_AGENT, PEER, PEER_AGENT, INTERNAL = 'me', 'my_agent', 'peer', 'peer_agent', 'internal'

    def _role_label(self, role: str, peer: str) -> str:
        return {self.ME: '我', self.MY_AGENT: '我的 Agent', self.PEER: f'{peer}本人',
                self.PEER_AGENT: f'{peer}的 Agent', self.INTERNAL: '我的 Agent（内部）'}[role]

    @staticmethod
    def _decision_text(summary: str) -> str:
        if summary.startswith('Need to confirm '):
            return f"「{summary[len('Need to confirm '):]}」还不确定，要问我本人"
        return {
            'All stated conditions pass': '对方的条件我都满足',
            'A required condition does not match': '有条件不满足',
            'Required facts no longer establish a match': '条件已不再满足',
            'No additional requirement needed': '不需要再补充要求',
            'Request ready for peer delivery': '需求已准备好，发给各位候选',
            'Waiting for missing condition evidence': '等待缺少的信息',
            'Waiting for further evidence': '等待更多信息',
        }.get(summary, summary)

    def _question_text(self, event: dict, peer: str) -> str:
        """Say who must answer and why: my own preference, or a fact about me."""
        question = next((q for q in self._snapshot.get('questions') or []
                         if q.get('question_id') == (event.get('payload') or {}).get('question_id')), None)
        if question is None:
            return f"需要我本人补充：{event.get('summary') or ''}"
        label = self._field_label(str(question.get('field', '')))
        if question.get('kind') == 'additional_requirements':
            return f"这是我画像里没定的偏好，要我本人决定：{question.get('title') or label}（会同步给所有候选）"
        return f"{peer} 那边要求对方「{label}」，我的 Agent 不知道，需要我本人确认：我是这样吗？"

    def _conversation_parts(self, event: dict) -> tuple[str, str | None, str]:
        """(speaker role, target role or None, text) for one event."""
        kind = event.get('type', '')
        peer = self._peer_name(event.get('peer_id'))
        payload = event.get('payload') or {}
        summary = str(event.get('summary') or '')
        detail = self._event_detail(event)
        requester = self._session_role(event.get('session_id')) == 'requester'
        me, agent, them, their_agent, inner = self.ME, self.MY_AGENT, self.PEER, self.PEER_AGENT, self.INTERNAL
        if kind == 'REQUEST_SENT':
            return agent, their_agent, '发出需求' + (f"：{detail.removeprefix('需求: ')}" if detail else '')
        if kind == 'REQUEST_RECEIVED':
            return their_agent, agent, '发来需求' + (f"：{detail.removeprefix('需求: ')}" if detail else '')
        if kind == 'FILTER_RESULT':
            return inner, None, f'对照我的画像核对 {peer} 的需求' + (f'：{detail}' if detail else '')
        if kind == 'FILTERED':
            return inner, None, f'我不满足 {peer} 的硬条件，本轮结束' + (f'：{detail}' if detail else '')
        if kind == 'NO_MATCH':
            return their_agent, agent, '对方不满足条件，本轮结束' + (f'：{detail}' if detail else '')
        if kind == 'POLICY_DECISION':
            text = self._decision_text(summary)
            return inner, None, f'关于 {peer}：{text}' + (f' · {detail}' if detail else '')
        if kind == 'QUESTION':
            return agent, me, self._question_text(event, peer)
        if kind == 'ANSWER':
            who = me
            text = f'回答：{detail}' if detail else '已回答'
            if payload.get('proxy'):
                text += '（演示脚本代答）'
            return who, agent, text
        if kind == 'PROPOSAL':
            return agent, their_agent, '条件都对上了，发出见面提案' + (f' · {detail}' if detail else '')
        if kind == 'PENDING_APPROVAL':
            if requester:
                return agent, me, f'与 {peer} 的提案已就绪，等我选择'
            return agent, me, f'与 {peer} 的提案已就绪，等 {peer}本人 选择'
        if kind == 'APPROVAL':
            if summary == 'Owner approved proposal':
                return (me, them, f'我选定了 {peer}，等对方确认') if requester else (me, them, f'我接受了 {peer} 的选择')
            return (them, me, f'{peer}本人 接受了我的选择') if requester else (them, me, f'{peer}本人 选择了我，等我确认')
        if kind == 'CONNECTED':
            return me, them, '双方本人都已确认，见面提案已生成'
        if kind == 'REJECTED':
            if summary == 'Owner rejected proposal':
                return me, them, f'我婉拒了 {peer}' if requester else f'我婉拒了 {peer} 的选择'
            if payload.get('reason') == 'owner rejected proposal':
                if requester:
                    return them, me, f'{peer}本人 婉拒了我的选择，可以在剩下的候选里重新选'
                return them, me, f'{peer}本人 选择了其他人'
            return their_agent, agent, f'{self._decision_text(summary)}，本轮结束'
        if kind == 'CHAT_SENT':
            return me, their_agent, f'问：{summary}'
        if kind == 'CHAT_REPLY':
            return their_agent, me, f'答：{summary}'
        if kind == 'CHAT_RECEIVED':
            return them, agent, f'问：{summary}'
        if kind == 'CHAT_REPLIED':
            return agent, them, f'（替我）答：{summary}'
        if kind == 'PROCESSING_ERROR':
            return inner, None, f'处理出错：{summary}' + (f' · {detail}' if detail else '')
        return inner, None, summary + (f' · {detail}' if detail else '')

    def _conversation_line(self, event: dict) -> str:
        speaker, target, text = self._conversation_parts(event)
        peer = self._peer_name(event.get('peer_id'))
        heading = self._role_label(speaker, peer) + (f' → {self._role_label(target, peer)}' if target else '')
        return f'{heading}\n  {text}\n'

    def _session_role(self, session_id) -> str | None:
        session = next((s for s in self._snapshot.get('sessions') or [] if s.get('session_id') == session_id), None)
        return (session or {}).get('role')

    def _field_label(self, field: str) -> str:
        config = getattr(self.runtime, "config", {}) or {}
        scenario = config.get("scenario") or {}
        return str((scenario.get("fields") or {}).get(field, {}).get("label") or field)

    @staticmethod
    def _display_value(value: Any) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        return str(value)

    def _format_requirement(self, item: dict) -> str:
        label = self._field_label(str(item.get("field", "?")))
        op = {"eq": "=", "gte": "≥", "lte": "≤", "contains": "包含"}.get(item.get("op"), str(item.get("op", "?")))
        return f"{label} {op} {self._display_value(item.get('value'))}"

    def _event_detail(self, event: dict) -> str:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return ""
        kind = event.get("type")
        if kind in {"REQUEST_SENT", "REQUEST_RECEIVED"}:
            requirements = payload.get("requirements") or []
            if requirements:
                return "需求: " + ", ".join(self._format_requirement(item) for item in requirements if isinstance(item, dict))
        if kind in {"FILTER_RESULT", "FILTERED", "NO_MATCH"}:
            reasons = payload.get("reasons") or []
            if reasons:
                return "; ".join(
                    f"{self._field_label(str(item.get('field', '?')))}: " +
                    ({'PASS':'符合', 'FAIL':'不符合', 'UNKNOWN':'需要确认'}.get(item.get('status'), str(item.get('status', '')))
                     if not self._debug else f"{item.get('status', '?')} — {item.get('reason', '')}")
                    for item in reasons if isinstance(item, dict)
                )
        if kind in {"QUESTION", "ANSWER"}:
            question_id = payload.get("question_id")
            question = next((q for q in self._snapshot.get("questions") or [] if q.get("question_id") == question_id), None)
            if question:
                field = self._field_label(str(question.get("field", "?")))
                if kind == "ANSWER" and "answer" in question:
                    return f"{field}: {question['answer']}"
                return f"{field} · {question.get('title') or question.get('reason') or ''}"
        if kind in {"PROPOSAL", "PENDING_APPROVAL", "CONNECTED"}:
            session_id = event.get("session_id")
            session = next((s for s in self._snapshot.get("sessions") or [] if s.get("session_id") == session_id), None)
            proposal = (session or {}).get("proposal") or {}
            if proposal.get("digest") == payload.get("digest"):
                terms = proposal.get("terms") or {}
                requirements = terms.get("requirements") or []
                if requirements:
                    return "提案: " + ", ".join(self._format_requirement(item) for item in requirements if isinstance(item, dict))
        if kind == "POLICY_DECISION":
            field = payload.get("field")
            return (f"{payload.get('action', '')}" + (f" · {self._field_label(str(field))}" if field else "")) if self._debug else ''
        if kind == "PROCESSING_ERROR" and payload.get("message_id"):
            message_id = str(payload["message_id"])
            return f"message {message_id} blocked · /retry {message_id}"
        if kind == "RETRY_REQUESTED" and payload.get("message_id"):
            return f"message {payload['message_id']}"
        return ""

    def _render_details(self) -> None:
        selected_session = self.query_one("#session-select", Select).value
        sessions = self._snapshot.get("sessions") or []
        session = next((s for s in sessions if s.get("session_id") == selected_session), None)
        if not self._debug and not (session and session.get('artifact')):
            session = next((s for s in sessions if s.get('artifact')), session)
        if session:
            lines = []
            artifact = session.get("artifact")
            if artifact:
                terms = artifact.get('terms') or {}
                lines = [artifact.get('title') or '合作结果', f"我 ↔ {self._peer_name(session.get('peer_id'))}", '双方已确认', '', '已达成的条件']
                lines += [self._format_requirement(r) for r in terms.get('requirements', [])]
                lines += ['', '已确认信息']
                lines += [f'{self._field_label(k)}：{self._display_value(v)}' for k, v in terms.get('provider_facts', {}).items()]
                lines += ['', artifact.get('next_step') or '双方安排下一步交流']
            self.query_one("#session-detail", Static).update("\n".join(lines))
        else:
            self.query_one("#session-detail", Static).update("No session selected")
        self.query_one('#details').display = bool(session and session.get('artifact'))
        self._render_loop_in()

    def _render_loop_in(self) -> None:
        panel = self.query_one('#owner-panel')
        field = self.query_one('#owner-input', Input)
        questions = [q for q in self._snapshot.get('questions', []) if not q.get('answered')]
        selected_question = self.query_one("#question-select", Select).value
        if self._draft_active and self._draft_question_id and not self._composer:
            selected_question = self._draft_question_id
        question = next((q for q in questions if q.get('question_id') == selected_question), None)
        stale_draft = bool(self._draft_active and self._draft_question_id and not question and not self._composer)
        if question is None and questions and not self._draft_active:
            question = questions[0]
            self.query_one('#question-select', Select).value = question['question_id']
        own_id = (self._snapshot.get('agent') or {}).get('agent_id')
        sessions = self._snapshot.get('sessions', [])
        # Requester pairs are decided through the choice panel; a provider is
        # asked only once the requester has chosen them (two-way consent).
        approvals = [s for s in sessions if s.get('state') == 'PENDING_APPROVAL' and s.get('proposal')
                     and own_id not in s.get('approvals', []) and s.get('role') != 'requester'
                     and (s.get('role') != 'provider' or s.get('peer_id') in s.get('approvals', []))]
        selected_session = self.query_one('#session-select', Select).value
        approval = next((s for s in approvals if s.get('session_id') == selected_session), approvals[0] if approvals else None)
        choices = self._choice_sessions()
        awaiting = self._awaiting_session()
        self._sync_chat_target(choices)
        target = next((s for s in choices if s['session_id'] == self._chat_target), None)
        manual = self._composer is not None
        self._needs_owner = bool(question or approval or choices or stale_draft) and not manual and not self._busy
        self._loop_session_id = None
        self._loop_question_id = question['question_id'] if question and not manual else None
        title, content, key = '', '', None
        input_visible = False
        if manual:
            key = ('composer', self._composer)
            title = '发起新需求' if self._composer == 'request' else '命令'
            content = '描述我的目标，提交后由 Agents 开始交流。' if self._composer == 'request' else '/help 查看命令 · Esc 返回交流'
            field.placeholder = '输入需求，Enter 广播' if self._composer == 'request' else '输入 /help、/retry 消息ID 等命令'
            input_visible = True
        elif stale_draft:
            key = ('stale', self._draft_question_id)
            title = '◆ 问题已更新 · 请检查草稿'
            content = '原问题已结束，草稿不会作为新需求发送。请清空输入框后继续。'
            input_visible = True
        elif question:
            key = ('question', question['question_id'])
            title = '◆ 需要我本人回答' + (f' · 还有 {len(questions)} 项' if len(questions) > 1 else '')
            session = next((s for s in sessions if s.get('session_id') == question.get('session_id')), {})
            peer = self._peer_name(session.get('peer_id'))
            label = self._field_label(str(question.get('field', '')))
            if question.get('kind') == 'additional_requirements':
                content = (f"我的 Agent 在问我一个偏好（我画像里没定）：\n{question.get('title') or label}\n"
                           "我的回答会作为新要求，同步给所有候选。")
            else:
                content = (f"{peer} 那边要求对方「{label}」。我的 Agent 不知道我是不是，\n"
                           f"需要我本人确认：我是否{label}？")
            field.placeholder = ('用自己的话回答，Enter 提交' if self._snapshot.get('mode') != 'deterministic'
                                 else '回答 是 或 否（数字题填数字），Enter 提交')
            input_visible = True
        elif awaiting:
            peer = self._peer_name(awaiting.get('peer_id'))
            key = ('awaiting', awaiting['session_id'])
            title = f'◆ 已选定 {peer} · 等待对方回应'
            content = (f"{peer} 接受后生成见面提案，其余候选随之婉拒；\n"
                       f"{peer} 婉拒的话，我可以在剩下的候选里重新选。")
        elif target:
            # Proposals wait on me: chat with the picked candidate's agent, then choose.
            peer = self._peer_name(target.get('peer_id'))
            key = ('choice', tuple(sorted(s['session_id'] for s in choices)))
            title = f'◆ 需要我选择 · {len(choices)} 选 1' if len(choices) > 1 else '◆ 需要我选择 · 还剩 1 位候选'
            content = ("直接打字 → 问对方的 Agent（按对方画像回答）\n"
                       "Ctrl+↑/↓ 或下拉框切换对象 · 想好了点「选定」，对方本人确认后成局")
            latest = self._latest_chat({target['session_id']})
            if latest:
                content += "\n\n" + latest
            field.placeholder = f"问 {peer} 的 Agent，例如：周末一般怎么过？"
            self.query_one('#choose-button', Button).label = f"选定 {peer}"
            input_visible = True
        elif approval:
            self._loop_session_id = approval['session_id']
            key = ('approval', approval['session_id'])
            peer = self._peer_name(approval.get('peer_id'))
            terms = approval['proposal'].get('terms') or {}
            requirements = '\n'.join(self._format_requirement(r) for r in terms.get('requirements', []))
            if approval.get('role') == 'provider':
                answered = sum(1 for e in self._snapshot.get('events') or []
                               if e.get('type') == 'CHAT_REPLIED' and e.get('session_id') == approval['session_id'])
                title = f'◆ {peer}本人 选择了我 · 是否接受？'
                # Compact: candidate windows are short in the demo layout.
                conditions = ' · '.join(self._format_requirement(r) for r in terms.get('requirements', []))
                content = (f"条件：{conditions}\n"
                           + (f"我的 Agent 刚才替我回答了 {answered} 个问题（见上方）。" if answered else '')
                           + "接受即生成见面提案。")
            else:
                title = '◆ 需要我确认 · 见面方案'
                content = f"与 {peer} 的提案\n{requirements}\n批准后等待双方确认；拒绝则结束本轮。"
            provider = approval.get('role') == 'provider'
            self.query_one('#approve-button', Button).label = '接受' if provider else '批准方案'
            self.query_one('#reject-button', Button).label = '婉拒' if provider else '拒绝方案'
        panel.display = key is not None and not self._busy
        field.display = input_visible
        choosing = bool(key and key[0] == 'choice')
        self.query_one('#choice-bar').display = choosing
        self.query_one('#choose-button').display = choosing
        self.query_one('#question-select').display = len(questions) > 1 and not manual
        self.query_one('#loop-title', Static).update(title)
        self.query_one('#question-detail', Static).update(content)
        if self._loop_error and not self._busy and self._error_question_id != self._loop_question_id:
            self._loop_error = ''
        self.query_one('#loop-error', Static).update(self._loop_error)
        self.query_one('#loop-error').display = bool(self._loop_error)
        self.query_one('#owner-actions').display = bool(self._loop_session_id) or manual or choosing
        self.query_one('#close-composer').display = manual
        for button_id in ('approve-button', 'reject-button'):
            self.query_one(f'#{button_id}').display = bool(self._loop_session_id)
        if not self._needs_owner:
            panel.remove_class('pulse')
        if panel.display and key != self._loop_key and not self._draft_active:
            (field if input_visible else self.query_one('#approve-button', Button)).focus()
        if not panel.display and self._loop_key is not None:
            self.query_one('#events', RichLog).focus()
        self._loop_key = key if panel.display else None
        pending = (self._snapshot.get('metrics') or {}).get('pending_inbox', 0)
        chat_phase = self._pending_chat_phase()
        spinning = bool(chat_phase or self._busy or pending)
        if chat_phase:
            phase = chat_phase
        elif self._busy or pending:
            phase = 'Agent 正在交流…'
        elif self._needs_owner:
            phase = '◆ 等我操作'
        elif awaiting:
            phase = f"● 等待 {self._peer_name(awaiting.get('peer_id'))} 回应…"
        elif any(s.get('state') == 'PENDING_APPROVAL' and s.get('role') == 'provider'
                 and s.get('peer_id') not in s.get('approvals', []) for s in sessions):
            phase = '● 提案已就绪 · 等待对方选择…'
        elif any(s.get('state') == 'PENDING_APPROVAL' for s in sessions):
            phase = '● 等待对方确认'
        elif any(s.get('state') in {'ACTIVE', 'PROPOSED', 'WAITING_INPUT'} for s in sessions):
            phase = '● Agents 交流中 · 暂不需要我操作'
        else:
            phase = '● Agent 待命 · 收到需求后自动交流'
        self._phase_text, self._phase_spinning = phase, spinning
        self._show_phase()

    def _pending_chat_phase(self) -> str:
        """Thinking text while a chat question waits for its model reply."""
        events = self._snapshot.get('events') or []
        done = {(e.get('payload') or {}).get('chat_id') for e in events if e.get('type') in {'CHAT_REPLY', 'CHAT_REPLIED'}}
        for e in reversed(events):
            chat_id = (e.get('payload') or {}).get('chat_id')
            if chat_id in done:
                continue
            peer = self._peer_name(e.get('peer_id'))
            if e.get('type') == 'CHAT_SENT':
                return f'{peer} 的 Agent 正在想怎么回答…'
            if e.get('type') == 'CHAT_RECEIVED':
                return f'我的 Agent 正在替我回答 {peer}本人 的问题…'
        return ''

    def _pulse_loop_in(self) -> None:
        panel = self.query_one('#owner-panel')
        if self._needs_owner and panel.display and self.animation_level != 'none':
            panel.toggle_class('pulse')
        else:
            panel.remove_class('pulse')

    def action_new_request(self) -> None:
        self._open_composer('request')

    def action_commands(self) -> None:
        self._open_composer('commands')

    def action_toggle_debug(self) -> None:
        self._debug = not self._debug
        self._last_event_seq = 0
        self.query_one('#events', RichLog).clear()
        self.refresh_from_runtime()

    def _open_composer(self, kind: str) -> None:
        if self._busy:
            return
        if self._draft_active:
            self._set_status('请先提交或清空当前草稿，再切换输入用途。')
            return
        self._composer = kind
        self._draft_question_id = None
        self._render_loop_in()

    def action_close_composer(self) -> None:
        if self._composer and not self._busy:
            self.query_one('#owner-input', Input).value = ''
            self._draft_active = False
            self._draft_question_id = None
            self._composer = None
            self._render_loop_in()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == 'new-request':
            self.action_new_request()
        elif button_id == 'commands':
            self.action_commands()
        elif button_id == 'close-composer':
            self.action_close_composer()
        elif button_id in {'approve-button', 'reject-button'} and self._loop_session_id and not self._busy:
            command = '/approve' if button_id == 'approve-button' else '/reject'
            self._start_action(f'{command} {self._loop_session_id}', None)
        elif button_id == 'choose-button' and self._chat_target and not self._busy:
            self._start_action('/choose', None)

    def on_select_changed(self, _event: Select.Changed) -> None:
        if _event.select.id == 'chat-target':
            if isinstance(_event.value, str) and _event.value != self._chat_target:
                self._chat_target = _event.value
                self._render_loop_in()
                self.query_one('#owner-input', Input).focus()
            return
        if (_event.select.id == 'question-select' and self._draft_active and self._draft_question_id
                and self._draft_question_id in {value for _, value in self._question_options}
                and _event.value != self._draft_question_id):
            _event.select.value = self._draft_question_id
        try:
            self._render_details()
        except NoMatches:
            # Switching details queues Select events; they may arrive after
            # child widgets have been removed during terminal shutdown.
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "owner-input":
            return
        if event.value and event.value != self._failed_text:
            self._loop_error = ''
        if event.value and not self._draft_active:
            selected = self.query_one("#question-select", Select).value
            self._draft_question_id = selected if isinstance(selected, str) and not self._composer else None
            self._draft_active = True
        elif not event.value:
            self._draft_active = False
            self._draft_question_id = None
        self.query_one('#question-select', Select).disabled = self._draft_active
        self._render_loop_in()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_input()

    def _submit_input(self) -> None:
        field = self.query_one('#owner-input', Input)
        line = field.value.strip()
        if not line or self._busy:
            return
        draft_question_id = self._draft_question_id
        original_text = line
        field.value = ''
        # The Changed('') message lands after the next render; without this the
        # same panel (e.g. the choice panel) reappears believing a draft is
        # open and never takes the keyboard back.
        self._draft_active = False
        self._start_action(line, draft_question_id, original_text)

    def _start_action(self, line: str, draft_question_id: str | None, original_text: str | None = None) -> None:
        self._busy = True
        self._render_loop_in()
        self.run_worker(self._handle_line(line, draft_question_id, original_text), exclusive=False)

    async def _handle_line(self, line: str, draft_question_id: str | None, original_text: str | None = None) -> None:
        restore_focus = False
        try:
            await self._dispatch(line, draft_question_id)
            self._composer = None
        except Exception as exc:
            self._set_status(f"没有成功：{exc}")
            self._loop_error = '✗ ' + self._friendly_error(exc)
            restored = original_text if original_text is not None else line
            self._failed_text = restored
            self._error_question_id = self._loop_question_id
            # Typed lines (original_text set) always come back for a quick fix.
            if draft_question_id or self._composer or original_text is not None:
                self.query_one('#owner-input', Input).value = restored
                self._draft_question_id = draft_question_id
                self._draft_active = True
                restore_focus = True
        finally:
            self._busy = False
            self.refresh_from_runtime()
            if restore_focus:
                self.query_one('#owner-input', Input).focus()

    async def _dispatch(self, line: str, draft_question_id: str | None) -> None:
        parts = line.split(maxsplit=2)
        command = parts[0].lower() if parts else ""
        if command == "/help":
            self._set_status("/request TEXT · /answer ID TEXT · /remember ID TEXT · /approve [SESSION_ID] · /reject [SESSION_ID] · @名字 问题 · /choose 名字 · /retry MESSAGE_ID · /sessions")
            return
        if line.startswith("@"):
            name, _, text = line[1:].partition(" ")
            if not text.strip():
                raise ValueError("需要补充：格式是 @名字 问题，例如 @陈语桐 她周末一般怎么过？")
            session = self._choice_by_name(name)
            self._chat_target = session["session_id"]
            await self.runtime.chat(session["session_id"], text.strip())
            self._set_status(f"已发给 {self._peer_name(session.get('peer_id'))} 的 Agent")
            return
        if command == "/choose":
            if len(parts) > 2:
                raise ValueError("需要补充：格式是 /choose 或 /choose 名字")
            session = self._choice_by_name(parts[1]) if len(parts) == 2 else \
                next((s for s in self._choice_sessions() if s["session_id"] == self._chat_target), None)
            if session is None:
                raise ValueError("需要补充：先在下拉框里选一位候选")
            await self.runtime.choose(session["session_id"])
            self._set_status(f"已选定 {self._peer_name(session.get('peer_id'))}，等待对方确认")
            return
        if command == "/sessions":
            sessions = self._snapshot.get("sessions") or []
            self._set_status(" · ".join(f"{s.get('session_id')}:{s.get('state')}" for s in sessions) or "No sessions")
            return
        if command == "/retry":
            if len(parts) != 2:
                raise ValueError("usage: /retry MESSAGE_ID")
            self.runtime.retry_blocked_message(parts[1])
            self._set_status(f"Retry requested for {parts[1]}")
            return
        if command == "/request":
            if len(parts) < 2 or not line.partition(" ")[2].strip():
                raise ValueError("usage: /request TEXT")
            await self.runtime.broadcast(line.partition(" ")[2].strip())
            self._set_status("需求已发出")
            return
        if command in {"/answer", "/remember"}:
            if len(parts) < 3:
                raise ValueError(f"usage: {command} QUESTION_ID TEXT")
            await self._answer(parts[1], parts[2], remember=command == "/remember")
            return
        if command in {"/approve", "/reject"}:
            if len(parts) > 2:
                raise ValueError(f"usage: {command} [SESSION_ID]")
            selected = self.query_one("#session-select", Select).value
            session_id = parts[1] if len(parts) == 2 else selected
            if not isinstance(session_id, str):
                raise ValueError("select a session or provide SESSION_ID")
            await self._approve(session_id, command == "/approve")
            return
        if line.startswith("/"):
            raise ValueError(f"unknown command: {command}")
        if draft_question_id:
            await self._answer(draft_question_id, line)
        elif self._choice_sessions() and not self._composer:
            # At the choice stage plain text goes to the picked candidate,
            # never into a brand-new broadcast.
            session = next((s for s in self._choice_sessions() if s["session_id"] == self._chat_target), None)
            if session is None:
                raise ValueError("需要补充：先在下拉框里选一位候选")
            await self.runtime.chat(session["session_id"], line)
            self._set_status(f"已发给 {self._peer_name(session.get('peer_id'))} 的 Agent")
        else:
            await self.runtime.broadcast(line)
            self._set_status("需求已发出")

    async def _answer(self, question_id: str, text: str, *, remember: bool = False) -> None:
        question = next((q for q in self._snapshot.get("questions") or [] if q.get("question_id") == question_id and not q.get("answered")), None)
        if question is None:
            raise ValueError(f"pending question not found: {question_id}")
        if remember and (question.get("kind") != "fact" or question.get("scope") != "session"):
            raise ValueError("only a confirmed personal fact can be remembered")
        await self.runtime.answer(question_id, text, remember=remember, expected_revision=question.get("revision"))
        self._set_status("已回答，我的 Agent 继续交流" + ("（已记住）" if remember else ""))

    async def _approve(self, session_id: str, approve: bool) -> None:
        session = next((s for s in self._snapshot.get("sessions") or [] if s.get("session_id") == session_id), None)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        proposal = session.get("proposal")
        if not proposal or not proposal.get("digest"):
            raise ValueError(f"no proposal displayed for {session_id}")
        await self.runtime.approve(session_id, approve, proposal_digest=proposal["digest"], expected_revision=session.get("revision"))
        peer = self._peer_name(session.get("peer_id"))
        self._set_status(f"我接受了 {peer} 的选择" if approve else f"我婉拒了 {peer}")

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc)
        if text.endswith('answer must be yes/no'):
            return '还不能确定我的意思，请补充说明。'
        if text.endswith('answer must be a number'):
            return '这里需要一个数字，例如 20。'
        if text.endswith('answer must be text'):
            return '回答不能为空。'
        if 'stale' in text or 'already answered' in text:
            return '问题已更新，请重新查看后再回答。'
        if text.startswith('需要补充：'):
            return text
        return f'提交失败：{text}'

    def _set_status(self, message: str) -> None:
        try:
            self.query_one("#status", Static).update(message)
        except NoMatches:
            # A pending poll may finish during Textual's test or terminal shutdown.
            pass
