const $ = (selector) => document.querySelector(selector);
const el = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
};
const append = (parent, ...children) => { children.filter(Boolean).forEach((child) => parent.append(child)); return parent; };
const clone = (value) => structuredClone(value);
const uid = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const modeKey = (mode) => `xagent.day1.${mode}.sessionId`;
const formatValue = (value) => typeof value === 'boolean' ? (value ? '是' : '否') : String(value ?? '—');
const stateLabels = { READY: '准备中', NEGOTIATING: '协商中', WAITING_INPUT: '等待本人回答', PENDING_APPROVAL: '待双方确认', CONNECTED: '双方已确认', NO_MATCH: '条件不匹配', DECLINED: '已拒绝', CANCELLED: '已取消', ERROR: '发生错误' };
const actorLabels = { 'agent-a': '林澈的代理', 'agent-b': '陈予的代理', 'owner-a': '林澈', 'owner-b': '陈予', system: '协商系统' };
const termLabels = { start_in_days: '全职加入时间', hours_per_week: '每周投入', trial_days: '试合作', requires_ai_experience: '要求 AI 产品经验', ai_product_experience: 'AI 产品经验' };
const termValue = (key, value) => key === 'start_in_days' ? `${value} 天后` : key === 'hours_per_week' ? `${value} 小时` : key === 'trial_days' ? `${value} 天` : key === 'ai_product_experience' ? (value ? '自述具备' : '未提供') : formatValue(value);

let mode = new URLSearchParams(location.search).get('mode') === 'api' ? 'api' : 'sample';
let owner = localStorage.getItem('xagent.day1.owner') === 'owner-b' ? 'owner-b' : 'owner-a';
let selectedCandidate = 'agent-b';
let demo = null;
let session = null;
let artifact = null;
let busy = false;
let transport;

class ApiTransport {
  async request(path, options = {}, authorized = true) {
    const headers = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (authorized) headers.Authorization = `Bearer demo-${owner}`;
    let response;
    try { response = await fetch(path, { ...options, headers: { ...headers, ...options.headers }, cache: 'no-store' }); }
    catch { const error = new Error('本地 API 无法连接。请确认服务已启动，然后重试；页面不会自动切换到样例数据。'); error.network = true; throw error; }
    let data;
    try { data = await response.json(); }
    catch { throw new Error(`API 返回了无法读取的响应（HTTP ${response.status}）。`); }
    if (!response.ok) { const error = new Error(data?.error?.message || `请求失败（HTTP ${response.status}）。`); error.status = response.status; throw error; }
    return data;
  }
  async mutate(path, payload) {
    const storageKey = 'xagent.day1.api.pending';
    let pending;
    try { pending = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch { pending = {}; }
    const key = JSON.stringify({ path, payload });
    const messageId = pending[key] || uid();
    pending[key] = messageId;
    localStorage.setItem(storageKey, JSON.stringify(pending));
    const result = await this.request(path, { method: 'POST', body: JSON.stringify({ ...payload, message_id: messageId }) });
    delete pending[key];
    localStorage.setItem(storageKey, JSON.stringify(pending));
    return result;
  }
  getDemo() { return this.request('/api/demo', {}, false); }
  create(candidateAgentId) { return this.mutate('/api/sessions', { scenario_id: demo.scenario.id, candidate_agent_id: candidateAgentId }); }
  get(sessionId) { return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`); }
  answer(sessionId, questionId, answer, revision) { return this.mutate(`/api/sessions/${encodeURIComponent(sessionId)}/answers`, { question_id: questionId, answer, expected_revision: revision, scope: 'session' }); }
  approve(sessionId, digest, approve, revision) { return this.mutate(`/api/sessions/${encodeURIComponent(sessionId)}/approvals`, { proposal_digest: digest, approve, expected_revision: revision }); }
  getArtifact(sessionId) { return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/artifact`); }
}

class SampleTransport {
  constructor() { this.fixture = null; this.storageKey = 'xagent.day1.sample.session'; }
  async load() {
    if (this.fixture) return;
    const response = await fetch('./fixtures/demo.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('样例文件无法读取。请通过本地 HTTP 服务打开工作台。');
    this.fixture = await response.json();
  }
  async getDemo() { await this.load(); return clone(this.fixture.demo); }
  save(value) { localStorage.setItem(this.storageKey, JSON.stringify(value)); return clone(value); }
  async get(sessionId) {
    const raw = localStorage.getItem(this.storageKey);
    if (!raw) throw new Error('没有找到这场样例协商。');
    const value = JSON.parse(raw);
    if (value.session_id !== sessionId) throw new Error('样例会话编号不匹配。');
    if (value.candidate_agent_id === 'agent-c' && owner !== 'owner-a') throw new Error('当前演示身份不是这场会话的参与者。');
    return clone(value);
  }
  event(s, actor, type, publicSummary) {
    s.events.push({ seq: s.events.length + 1, session_id: s.session_id, timestamp: new Date().toISOString(), actor, type, public_summary: publicSummary, payload: {}, mode: 'deterministic' });
  }
  async create(candidateAgentId) {
    if (owner !== 'owner-a') throw new Error('只有林澈可以发起这场合成协商。');
    await this.load();
    const s = clone(this.fixture.waiting_session);
    s.session_id = `sample-${uid()}`;
    s.candidate_agent_id = candidateAgentId;
    s.events.forEach((item, index) => { item.session_id = s.session_id; item.timestamp = new Date(Date.now() + index * 1000).toISOString(); });
    if (candidateAgentId === 'agent-c') {
      s.state = 'NO_MATCH'; s.revision = 2; s.rounds = 1; s.pending_question = null; s.events = [];
      s.terms = { start_in_days: 90, hours_per_week: 2, trial_days: 0, requires_ai_experience: false, ai_product_experience: false };
      this.event(s, 'agent-a', 'OPEN', '林澈的代理要求合伙人每周至少投入 15 小时。');
      this.event(s, 'system', 'HARD_CONSTRAINT_REJECTED', '候选人 C 每周只能投入 2 小时，未满足 15 小时的硬性要求，协商结束。');
    }
    return this.save(s);
  }
  async answer(sessionId, questionId, answer, revision) {
    const s = await this.get(sessionId);
    if (owner !== 'owner-a') throw new Error('只有林澈可以回答这张问题卡。');
    if (s.state !== 'WAITING_INPUT' || s.pending_question?.question_id !== questionId) throw new Error('这张问题卡已经失效。');
    if (s.revision !== revision) throw new Error('会话已更新，请刷新后再回答。');
    if (!['accept_90_days', 'require_ai_experience', 'decline'].includes(answer)) throw new Error('无效的回答。');
    const label = s.pending_question.options.find((option) => option.value === answer)?.label ?? answer;
    s.pending_question = null; s.revision += 1;
    this.event(s, 'owner-a', 'ANSWER', `林澈回答了关键问题：「${label}」。此决定只应用于当前协商。`);
    if (answer === 'decline') {
      s.state = 'NO_MATCH'; this.event(s, 'system', 'NO_MATCH', '林澈决定不继续，协商结束。');
      return this.save(s);
    }
    s.profile_versions['owner-a'] += 1;
    if (answer === 'require_ai_experience') s.terms.requires_ai_experience = true;
    this.event(s, 'agent-a', 'RESUME', '收到林澈的回答，原会话中的协商继续。');
    this.event(s, 'agent-b', 'PROPOSAL', answer === 'require_ai_experience' ? '陈予确认自己有 AI 产品经验；该经历为本人自述，双方形成待确认的合作提案。' : '陈予接受在 90 天后全职加入的安排，双方形成待确认的合作提案。');
    s.state = 'PENDING_APPROVAL'; s.rounds += 1;
    s.proposal = { version: 1, digest: `sample-proposal-${s.session_id}`, terms: clone(s.terms) };
    this.event(s, 'system', 'PENDING_APPROVAL', '回答已纳入本场协商；仍需双方分别确认提案，才会生成合作结果。');
    return this.save(s);
  }
  async approve(sessionId, digest, approval, revision) {
    const s = await this.get(sessionId);
    if (s.state !== 'PENDING_APPROVAL' || s.proposal?.digest !== digest) throw new Error('提案已更新或不可确认，请刷新会话。');
    if (s.revision !== revision) throw new Error('会话已更新，请刷新后再确认。');
    if (s.approvals.some((item) => item.owner_id === owner)) throw new Error('当前身份已经做过确认。');
    s.revision += 1;
    s.approvals.push({ owner_id: owner, proposal_digest: digest, approve: approval });
    this.event(s, owner, approval ? 'APPROVED' : 'DECLINED', approval ? `${actorLabels[owner]}确认了合作提案。` : `${actorLabels[owner]}拒绝了合作提案。`);
    if (!approval) { s.state = 'DECLINED'; return this.save(s); }
    if (s.approvals.length === 2) {
      s.state = 'CONNECTED';
      s.artifact = { session_id: s.session_id, scenario_id: s.scenario_id, terms: clone(s.terms), consents: clone(s.approvals), next_step: '双方自行安排一次初步沟通，确认试合作的时间与方式。', mode: 'deterministic' };
      this.event(s, 'system', 'CONNECTED', '双方均已确认同一提案，合作结果已生成。');
    }
    return this.save(s);
  }
  async getArtifact(sessionId) { const s = await this.get(sessionId); if (s.state !== 'CONNECTED') throw new Error('双方尚未确认，结果不可读取。'); return clone(s.artifact); }
}

function setNotice(message, error = false) {
  const node = $('#notice');
  node.hidden = !message; node.textContent = message || ''; node.classList.toggle('error', error);
}
function setBusy(value) { busy = value; document.querySelectorAll('button, select').forEach((item) => { item.disabled = value; }); }
async function run(action) {
  if (busy) return;
  setBusy(true); setNotice('');
  try { await action(); render(); }
  catch (error) {
    let restored = false;
    if (mode === 'api' && session && (error?.status === 409 || error?.network)) {
      try { session = await transport.get(session.session_id); if (session.state === 'CONNECTED') artifact = await transport.getArtifact(session.session_id); render(); restored = true; }
      catch { /* Keep the existing view and the original actionable error. */ }
    }
    render();
    setNotice(restored ? '已从服务端读取最新会话。请核对当前状态后继续。' : error?.message || '操作未完成，请重试。', !restored);
  }
  finally { setBusy(false); }
}
function saveSession(value) { session = value; localStorage.setItem(modeKey(mode), value.session_id); }
async function loadSession() {
  session = null; artifact = null;
  const sessionId = localStorage.getItem(modeKey(mode));
  if (!sessionId) return;
  try {
    session = await transport.get(sessionId);
    if (session.state === 'CONNECTED') artifact = await transport.getArtifact(sessionId);
  } catch (error) {
    setNotice(`${mode === 'api' ? 'API 模式' : '样例模式'}无法恢复会话：${error.message}`, true);
  }
}
async function loadWorkspace() {
  transport = mode === 'api' ? new ApiTransport() : new SampleTransport();
  demo = null; session = null; artifact = null;
  $('#mode-badge').textContent = mode === 'api' ? '本地 API · 确定性' : '本地样例 · 确定性';
  setNotice('');
  try {
    demo = await transport.getDemo();
    await loadSession();
  } catch (error) {
    setNotice(`${mode === 'api' ? 'API 模式' : '样例模式'}加载失败：${error.message}`, true);
  }
  render();
}
function renderProfile() {
  const root = $('#profile-card'); root.replaceChildren();
  const profile = demo?.profiles?.find((item) => item.owner_id === owner);
  if (!profile) { root.append(el('p', '', '资料暂不可用。')); return; }
  const top = el('div', 'profile-top');
  append(top, el('div', 'avatar', profile.name?.slice(0, 1) || '人'), el('h3', 'profile-name', profile.name), el('p', 'profile-role', profile.role), el('p', 'profile-summary', profile.summary));
  const body = el('div', 'profile-body'); body.append(el('div', 'detail-label', '公开事实 / PUBLIC FACTS'));
  for (const fact of profile.facts || []) {
    if (fact.visibility !== 'public') continue;
    const row = el('div', 'fact-row'); const value = el('div', 'fact-value', formatValue(fact.value));
    value.append(el('span', 'source-note', fact.source === 'self-reported' ? '本人自述 · 未核实' : '资料提供者填写'));
    append(row, el('span', '', fact.label), value); body.append(row);
  }
  if (profile.requirements?.length) {
    body.append(el('div', 'detail-label', '条件与待确认项 / CONDITIONS'));
    for (const requirement of profile.requirements) {
      const row = el('div', 'requirement-row');
      const requirementText = requirement.kind === 'ask' ? `待本人确认 ${requirement.value}${requirement.field === 'start_in_days' ? ' 天' : ''}` : `${requirement.operator === '>=' ? '至少 ' : requirement.operator + ' '}${requirement.value}${requirement.field === 'hours_per_week' ? ' 小时' : ''}`;
      append(row, el('span', '', requirement.label), el('span', 'requirement-value', requirementText)); body.append(row);
    }
  }
  append(root, top, body, el('div', 'card-foot', `公开资料 v${profile.version} · 合成演示身份切换`));
}
function renderCandidates() {
  const root = $('#candidate-list'); root.replaceChildren();
  for (const candidate of demo?.candidates || []) {
    const button = el('button', `candidate-button${selectedCandidate === candidate.agent_id ? ' selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-pressed', selectedCandidate === candidate.agent_id ? 'true' : 'false');
    const top = el('div', 'candidate-top'); append(top, el('span', 'candidate-name', candidate.name), el('span', `candidate-status${candidate.eligible ? '' : ' blocked'}`, candidate.eligible ? '可协商' : '条件不符'));
    append(button, top, el('div', 'candidate-role', candidate.role), el('p', 'candidate-summary', candidate.summary), el('span', 'candidate-reason', candidate.reason));
    button.addEventListener('click', () => { selectedCandidate = candidate.agent_id; renderCandidates(); renderAction(); });
    root.append(button);
  }
}
function formatTime(timestamp) { const time = new Date(timestamp); return Number.isNaN(time.getTime()) ? '' : time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }
function renderTimeline() {
  const root = $('#timeline'); root.replaceChildren();
  if (!session?.events?.length) {
    const empty = el('div', 'empty-timeline'); append(empty, el('div', 'empty-icon', '↗'), el('div', '', '选择候选人，发起一场公开条件协商。')); root.append(empty); return;
  }
  for (const event of session.events) {
    const actorClass = event.actor === 'agent-a' ? 'agent-a' : event.actor === 'agent-b' ? 'agent-b' : event.actor === 'system' ? 'system' : 'owner';
    const block = el('article', `event ${actorClass}`); const head = el('div', 'event-head');
    append(head, el('span', 'actor', actorLabels[event.actor] || event.actor), el('time', 'event-time', formatTime(event.timestamp)));
    append(block, head, el('div', 'event-body', event.public_summary)); root.append(block);
  }
}
function renderMeta() {
  const status = $('#session-status'); status.textContent = session ? stateLabels[session.state] || session.state : '未开始';
  status.className = `status-pill${session?.state === 'WAITING_INPUT' ? ' waiting' : session?.state === 'PENDING_APPROVAL' ? ' approval' : session?.state === 'CONNECTED' ? ' connected' : ['NO_MATCH', 'DECLINED'].includes(session?.state) ? ' ended' : ''}`;
  const meta = $('#session-meta'); meta.replaceChildren(); meta.hidden = !session;
  if (session) {
    const chips = [`会话 ${session.session_id.slice(0, 12)}…`, `修订 r${session.revision}`, `林澈资料 v${session.profile_versions?.['owner-a'] ?? '—'}`, `陈予资料 v${session.profile_versions?.['owner-b'] ?? '—'}`, `协商轮次 ${session.rounds ?? '—'}`];
    chips.forEach((item) => meta.append(el('span', 'meta-chip', item)));
  }
  $('#new-session-button').hidden = !session;
}
function actionShell(icon, eyebrow, title, description) {
  const root = $('#action-card'); root.replaceChildren();
  append(root, el('div', 'action-icon', icon), el('div', 'action-eyebrow', eyebrow), el('h3', '', title), el('p', '', description));
  return root;
}
function button(label, className, onClick) {
  const item = el('button', className, label); item.type = 'button'; item.addEventListener('click', onClick); return item;
}
async function startSession() {
  await run(async () => { const value = await transport.create(selectedCandidate); saveSession(value); artifact = null; });
}
async function submitAnswer(answer) {
  await run(async () => { const question = session.pending_question; saveSession(await transport.answer(session.session_id, question.question_id, answer, session.revision)); });
}
async function submitApproval(approval) {
  await run(async () => { saveSession(await transport.approve(session.session_id, session.proposal.digest, approval, session.revision)); if (session.state === 'CONNECTED') artifact = await transport.getArtifact(session.session_id); });
}
function renderStartAction() {
  const candidate = demo.candidates.find((item) => item.agent_id === selectedCandidate) || demo.candidates[0];
  if (owner !== 'owner-a') { actionShell('↗', 'START A CONVERSATION', '由林澈发起协商', '这场合成情境由技术创始人林澈发起。请用顶部的演示身份切换至林澈，再选择候选人。'); return; }
  const root = actionShell('↗', 'START A CONVERSATION', `与${candidate.name}开始协商`, candidate.eligible ? '公开条件将由双方代理依次交换；遇到需要你判断的问题，协商会暂停。' : `硬性条件检查会先执行：${candidate.reason}。`);
  root.append(button(candidate.eligible ? '发起协商 →' : '运行硬性条件检查 →', 'primary-button', startSession));
  root.append(el('p', 'subtle', '这是确定性演示，不会调用实时模型或联系真实用户。'));
}
function renderQuestionAction() {
  const question = session.pending_question;
  if (!question) { actionShell('⋯', 'WAITING', '正在等待问题', '刷新会话以获取最新进展。'); return; }
  const root = actionShell('?', 'DECISION REQUIRED', question.title, question.reason);
  if (question.owner_id !== owner) { root.append(el('p', 'scope-note', '这张问题卡需要林澈本人回答。请用顶部的合成演示身份切换至林澈。')); return; }
  const fieldset = el('fieldset', 'option-list'); fieldset.style.border = '0'; fieldset.style.padding = '0'; fieldset.style.minWidth = '0';
  const legend = el('legend', 'detail-label', '选择一个回答'); fieldset.append(legend);
  for (const option of question.options || []) {
    const label = el('label', 'option'); const input = el('input'); input.type = 'radio'; input.name = 'answer'; input.value = option.value;
    append(label, input, el('span', '', option.label)); fieldset.append(label);
  }
  root.append(fieldset, el('p', 'scope-note', '仅更新当前会话中的偏好；公开名片保持原版本。回答“接受 90 天”也不代表最终同意建立联系。'));
  root.append(button('提交回答，继续协商 →', 'primary-button', () => { const choice = root.querySelector('input[name="answer"]:checked'); if (!choice) { setNotice('请先选择一个回答。', true); return; } submitAnswer(choice.value); }));
}
function renderTerms(root, terms) {
  const list = el('ul', 'terms-list');
  for (const [key, value] of Object.entries(terms || {})) { const item = el('li'); append(item, el('span', '', termLabels[key] || key), el('strong', '', termValue(key, value))); list.append(item); }
  root.append(list);
}
function approvalOwner(item) { return typeof item === 'string' ? item : item?.owner_id; }
function renderApprovalAction() {
  const root = actionShell('✓', 'PENDING APPROVAL', '请确认合作提案', '关键问题已回答，协商在同一会话中继续。此处是正式确认，必须双方都同意才会生成结果。');
  renderTerms(root, session.proposal?.terms || session.terms);
  const approvals = session.approvals || [];
  for (const id of ['owner-a', 'owner-b']) {
    const row = el('div', 'approval-row'); append(row, el('span', '', actorLabels[id]), el('strong', '', approvals.some((item) => approvalOwner(item) === id) ? '已确认' : '待确认')); root.append(row);
  }
  if (approvals.some((item) => approvalOwner(item) === owner)) { root.append(el('p', 'scope-note', '你已确认。请切换到另一位合成演示身份，完成另一方的决定。')); return; }
  const stack = el('div', 'button-stack'); append(stack, button('同意此提案 →', 'primary-button', () => submitApproval(true)), button('拒绝此提案', 'danger-button', () => submitApproval(false))); root.append(stack);
}
function renderResultAction() {
  const root = actionShell('↗', 'CONNECTED', '双方已确认', '两位参与者已分别同意同一份提案。');
  renderTerms(root, artifact?.terms || session.terms);
  root.append(el('p', 'scope-note', artifact?.next_step || '双方可安排初步沟通，确认试合作安排。'));
  root.append(el('p', 'subtle', '这是合成演示结果，不包含真实联系信息。'));
}
function renderAction() {
  if (!demo) { actionShell('!', 'DATA UNAVAILABLE', '工作台暂不可用', mode === 'api' ? '请启动本地 API 服务并刷新页面。API 模式不会自动使用样例数据。' : '请通过本地 HTTP 服务打开页面，并检查样例文件。'); return; }
  if (!session) { renderStartAction(); return; }
  switch (session.state) {
    case 'WAITING_INPUT': renderQuestionAction(); break;
    case 'PENDING_APPROVAL': renderApprovalAction(); break;
    case 'CONNECTED': renderResultAction(); break;
    case 'NO_MATCH': actionShell('×', 'NO MATCH', '本场协商结束', '候选人未满足硬性条件，或本人决定不继续。你可以选择另一位候选人，开始新会话。'); break;
    case 'DECLINED': actionShell('×', 'DECLINED', '提案已拒绝', '至少一方拒绝了合作提案，这场协商已结束。'); break;
    default: actionShell('⋯', 'IN PROGRESS', stateLabels[session.state] || '协商进行中', '代理正在处理公开条件。请刷新会话查看最新状态。');
  }
}
function render() { $('.app-shell').classList.toggle('has-session', Boolean(session)); renderProfile(); renderCandidates(); renderMeta(); renderTimeline(); renderAction(); }

$('#mode-select').value = mode; $('#owner-select').value = owner;
$('#mode-select').addEventListener('change', async (event) => {
  mode = event.target.value;
  const url = new URL(location.href); url.searchParams.set('mode', mode); history.replaceState(null, '', url);
  await loadWorkspace();
});
$('#owner-select').addEventListener('change', async (event) => {
  owner = event.target.value; localStorage.setItem('xagent.day1.owner', owner);
  const sessionId = localStorage.getItem(modeKey(mode));
  if (sessionId) {
    setBusy(true); setNotice('');
    try { session = await transport.get(sessionId); artifact = session.state === 'CONNECTED' ? await transport.getArtifact(sessionId) : null; }
    catch (error) { session = null; artifact = null; setNotice(error?.message || '当前身份无法读取会话。', true); }
    finally { setBusy(false); }
  }
  render();
});
$('#new-session-button').addEventListener('click', () => { localStorage.removeItem(modeKey(mode)); session = null; artifact = null; setNotice(''); render(); });
loadWorkspace();
