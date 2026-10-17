"""One-owner Textual view over an already running AgentRuntime."""
from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, RichLog, Select, Static
from .profile import profile_view


class AgentApp(App):
    """Display local public state and route owner actions to this runtime only."""

    BINDINGS = [Binding("ctrl+n", "new_request", "发起需求", priority=True),
                Binding("ctrl+p", "commands", "命令", priority=True),
                Binding("ctrl+d", "toggle_debug", "详情", priority=True),
                ("escape", "close_composer", "返回交流")]

    CSS = """
    Screen { layout: vertical; }
    #profile-card { height: auto; max-height: 8; border: round $primary; margin: 0 1; padding: 0 1; }
    #identity { height: auto; text-style: bold; color: $text; }
    #profile { height: auto; max-height: 4; color: $text-muted; overflow-y: auto; }
    #toolbar { height: 3; padding: 0 1; }
    #toolbar Button { min-width: 10; width: auto; margin-right: 1; }
    #phase { height: 1; padding: 0 1; color: $text-muted; }
    #selectors { height: 3; }
    #session-select, #question-select { width: 1fr; margin: 0 1; }
    #body { height: 1fr; }
    #events { width: 2fr; height: 1fr; border: round $accent; margin: 0 1; }
    #details { width: 1fr; min-width: 20; height: 1fr; border: round $secondary; margin: 0 1; padding: 0 1; overflow-y: auto; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #owner-panel { height: auto; max-height: 60%; border: round $warning; margin: 0 1; padding: 0 1; background: $surface; }
    #owner-panel.pulse { border: round $accent; background: $warning 10%; }
    #loop-title { height: 1; text-style: bold; color: $warning; }
    #loop-error { height: auto; color: $error; text-style: bold; }
    #question-detail { height: auto; max-height: 8; overflow-y: auto; }
    #question-select { width: 1fr; margin: 0; }
    #owner-input { height: 3; }
    #owner-actions { height: 3; }
    #owner-actions Button { min-width: 14; width: auto; margin-right: 1; }
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
        with Vertical(id="profile-card"):
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
            yield Static("", id="question-detail", markup=False)
            yield Static("", id="loop-error", markup=False)
            yield Input(placeholder="输入你的回答，Enter 交还 Agent", id="owner-input")
            with Horizontal(id="owner-actions"):
                yield Button("批准方案", id="approve-button", variant="success")
                yield Button("拒绝方案", id="reject-button", variant="error")
                yield Button("返回交流", id="close-composer")
        yield Static("Ctrl+N 发起需求 · Ctrl+D 详情 · Ctrl+Q 退出", id="status", markup=False)

    def on_mount(self) -> None:
        self.refresh_from_runtime()
        self.set_interval(0.25, self.refresh_from_runtime)
        self.set_interval(0.75, self._pulse_loop_in)
        self.query_one("#events", RichLog).border_title = "AGENTS 先聊 · 实时交流"
        self.query_one('#profile-card').border_title = '我的 Agent · 用户名片'

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
        self.query_one('#selectors').display = bool((self._debug and sessions) or len(actionable) > 1 or len(results) > 1)
        self._render_details()

        log = self.query_one("#events", RichLog)
        for event in sorted(self._snapshot.get("events") or [], key=lambda x: int(x.get("seq") or 0)):
            seq = int(event.get("seq") or 0)
            if seq <= self._last_event_seq:
                continue
            log.write(self._conversation_line(event))
            self._last_event_seq = seq

    def _peer_name(self, peer_id) -> str:
        peers = (getattr(self.runtime, 'config', {}) or {}).get('peers', [])
        peer = next((p for p in peers if p.get('agent_id') == peer_id), {})
        return str(peer.get('name') or peer_id or '对方')

    def _conversation_line(self, event: dict) -> str:
        kind = event.get('type', '')
        peer = self._peer_name(event.get('peer_id'))
        payload = event.get('payload') or {}
        detail = self._event_detail(event)
        summary = str(event.get('summary') or '')
        headings = {
            'REQUEST_SENT': (f'我 → {peer}', '发送需求'),
            'REQUEST_RECEIVED': (f'{peer} → 我', '收到需求'),
            'FILTER_RESULT': (f'我的 Agent · 筛选 {peer}', '核对已知画像'),
            'FILTERED': (f'我的 Agent · 筛选 {peer}', '硬条件不匹配，本轮结束'),
            'NO_MATCH': (f'{peer} → 我', '条件不匹配，本轮结束'),
            'POLICY_DECISION': (f'我的 Agent · 决策 · {peer}', summary),
            'QUESTION': ('我的 Agent → 你', '需要补充信息'),
            'ANSWER': ('你 → 我的 Agent', '收到回答，继续交流'),
            'PROPOSAL': (f'我 → {peer}', '发出合作提案'),
            'PENDING_APPROVAL': ('我的 Agent → 你', f'已与 {peer} 形成提案，等待你确认'),
            'CONNECTED': (f'我 ↔ {peer}', '双方已批准，结果已生成'),
            'APPROVAL': (f'我 ↔ {peer}', '批准状态更新'),
            'REJECTED': (f'我 ↔ {peer}', self._rejected_text(peer, summary, payload)),
            'PROCESSING_ERROR': ('我的 Agent · 需要处理', summary),
        }
        heading, text = headings.get(kind, (kind or '进展', summary))
        return f'{heading}\n  {text}' + (f' · {detail}' if detail else '') + '\n'

    @staticmethod
    def _rejected_text(peer: str, summary: str, payload: dict) -> str:
        # Owner declines are recorded distinctly by the runtime; anything
        # else (e.g. the peer agent's own policy) keeps the neutral wording.
        if summary == 'Owner rejected proposal':
            return f'你婉拒了与 {peer} 的提案'
        if payload.get('reason') == 'owner rejected proposal':
            return f'{peer} 婉拒了提案（对方已选择其他人）'
        return '本轮协商已结束'

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
        approvals = [s for s in sessions if s.get('state') == 'PENDING_APPROVAL' and s.get('proposal')
                     and own_id not in s.get('approvals', [])]
        selected_session = self.query_one('#session-select', Select).value
        approval = next((s for s in approvals if s.get('session_id') == selected_session), approvals[0] if approvals else None)
        manual = self._composer is not None
        self._needs_owner = bool(question or approval or stale_draft) and not manual and not self._busy
        self._loop_session_id = None
        self._loop_question_id = question['question_id'] if question and not manual else None
        title, content, key = '', '', None
        input_visible = False
        if manual:
            key = ('composer', self._composer)
            title = '发起新需求' if self._composer == 'request' else '命令'
            content = '描述你的目标，提交后由 Agents 开始交流。' if self._composer == 'request' else '/help 查看命令 · Esc 返回交流'
            field.placeholder = '输入需求，Enter 广播' if self._composer == 'request' else '输入 /help、/retry 消息ID 等命令'
            input_visible = True
        elif stale_draft:
            key = ('stale', self._draft_question_id)
            title = '◆ 问题已更新 · 请检查草稿'
            content = '原问题已结束，草稿不会作为新需求发送。请清空输入框后继续。'
            input_visible = True
        elif question:
            key = ('question', question['question_id'])
            title = f'◆ 需要你参与 · 补充信息' + (f' · 待答 {len(questions)} 项' if len(questions) > 1 else '')
            session = next((s for s in sessions if s.get('session_id') == question.get('session_id')), {})
            scope = f"与 {self._peer_name(session.get('peer_id'))} 的交流" if question.get('scope') == 'session' else '本次需求 · 对所有候选生效'
            reason = question.get('reason') or question.get('title') or question.get('field')
            # Existing saved questions may still contain the old format instruction.
            reason = reason.replace('请回答是或否。', '').replace('回答是或否。', '')
            content = f"{scope}\n{reason}"
            field.placeholder = '用自己的话回答，Enter 提交'
            input_visible = True
        elif approval:
            self._loop_session_id = approval['session_id']
            key = ('approval', approval['session_id'])
            title = '◆ 需要你参与 · 确认方案'
            terms = approval['proposal'].get('terms') or {}
            requirements = '\n'.join(self._format_requirement(r) for r in terms.get('requirements', []))
            content = f"与 {self._peer_name(approval.get('peer_id'))} 的提案\n{requirements}\n批准后等待双方确认；拒绝则结束本轮。"
        panel.display = key is not None and not self._busy
        field.display = input_visible
        self.query_one('#question-select').display = len(questions) > 1 and not manual
        self.query_one('#loop-title', Static).update(title)
        self.query_one('#question-detail', Static).update(content)
        if self._loop_error and not self._busy and self._error_question_id != self._loop_question_id:
            self._loop_error = ''
        self.query_one('#loop-error', Static).update(self._loop_error)
        self.query_one('#loop-error').display = bool(self._loop_error)
        self.query_one('#owner-actions').display = bool(self._loop_session_id) or manual
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
        if self._busy or pending:
            phase = '● Agent 正在处理与交流…'
        elif self._needs_owner:
            phase = '◆ 等待你参与'
        elif any(s.get('state') == 'PENDING_APPROVAL' for s in sessions):
            phase = '● 等待对方确认'
        elif any(s.get('state') in {'ACTIVE', 'PROPOSED', 'WAITING_INPUT'} for s in sessions):
            phase = '● Agents 交流中 · 暂不需要你操作'
        else:
            phase = '● Agent 待命 · 收到需求后自动交流'
        self.query_one('#phase', Static).update(phase)

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

    def on_select_changed(self, _event: Select.Changed) -> None:
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
            self._set_status(f"Action error: {exc}")
            self._loop_error = '✗ ' + self._friendly_error(exc)
            restored = original_text if original_text is not None else line
            self._failed_text = restored
            self._error_question_id = self._loop_question_id
            if draft_question_id or self._composer:
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
            self._set_status("/request TEXT · /answer ID TEXT · /remember ID TEXT · /approve [SESSION_ID] · /reject [SESSION_ID] · /retry MESSAGE_ID · /sessions")
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
            self._set_status("Request submitted")
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
        else:
            await self.runtime.broadcast(line)
            self._set_status("Request submitted")

    async def _answer(self, question_id: str, text: str, *, remember: bool = False) -> None:
        question = next((q for q in self._snapshot.get("questions") or [] if q.get("question_id") == question_id and not q.get("answered")), None)
        if question is None:
            raise ValueError(f"pending question not found: {question_id}")
        if remember and (question.get("kind") != "fact" or question.get("scope") != "session"):
            raise ValueError("only a confirmed personal fact can be remembered")
        await self.runtime.answer(question_id, text, remember=remember, expected_revision=question.get("revision"))
        self._set_status(("Remembered " if remember else "Answered ") + question_id)

    async def _approve(self, session_id: str, approve: bool) -> None:
        session = next((s for s in self._snapshot.get("sessions") or [] if s.get("session_id") == session_id), None)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        proposal = session.get("proposal")
        if not proposal or not proposal.get("digest"):
            raise ValueError(f"no proposal displayed for {session_id}")
        await self.runtime.approve(session_id, approve, proposal_digest=proposal["digest"], expected_revision=session.get("revision"))
        self._set_status(("Approved " if approve else "Rejected ") + session_id)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc)
        if text.endswith('answer must be yes/no'):
            return '还不能确定你的意思，请补充说明。'
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
