# MVP shared integration contract

User authorized decentralized four-process TUI implementation. A owns models/scenario/storage/runtime/server; B owns policy/tui. Root owns launcher/configs/dependencies/process acceptance/docs. No worker commits/branch changes/nested agents.

## Config and scenario

Use JSON-compatible dictionaries at public boundaries to reduce cross-worker coupling. AgentRuntime accepts a config dict. Config keys: agent_id, owner_id, name, host (127.0.0.1), port, database, owner_token (local owner only), token (this agent's demo peer bearer), scenario (scenario dict), profile (facts dict, public_fields list, tags list), peers (list of {agent_id,name,url,token}). Each receiver verifies Bearer against the claimed known sender's configured token. Local owner endpoints require owner_token, which is distinct from token and is never included in the peer list. Demo tokens are synthetic, not production authentication.

Scenario: {id,name,fields:{field:{label,type,aliases:[],pattern?:string}},initial_requirements:[],followup:{field,title,prompt}?,result_title}. Field types boolean/number/string. Requirements {field,op,value}; ops eq,gte,lte,contains. initial_requirements are explicit fixture defaults only when caller supplies them; do not silently add them to a user's demand. Scenario followup is configurable, e.g. field ai_product_experience, title 是否还要求 AI 产品经验, prompt text; venue uses a different field. Generic core cannot branch on these field names.

A may add schema keys in coordination; send root/B an actual sample config early. No hidden tests-only behavior.

## Runtime facade

AgentRuntime(config:dict, policy=None). Attributes config, policy, mode. Async start(), stop(); start owns durable worker(s), stop cancels/awaits them. snapshot() returns dict synchronously (local read). Async broadcast(text:str, requirements:list|None=None)->dict; answer(question_id:str,text:str,remember:bool=False,expected_revision:int|None=None)->dict; approve(session_id:str,approve:bool,proposal_digest:str|None=None,expected_revision:int|None=None)->dict. All return updated snapshot or structured created demand with IDs; A announces final return shape early. Errors use normal typed exceptions with readable messages; TUI catches and renders, never silently drops.

snapshot keys: agent:{agent_id,name,port,profile}, mode, requests:[], sessions:[], questions:[], events:[], metrics:{}.
Session keys: session_id,request_id,peer_id,state,revision,requirements,terms,proposal (null or {digest,version,terms}),approvals:[],artifact:null|dict,pending_question_id:null|string.
Question keys: question_id,session_id:null|string,request_id,field,title,reason,kind (additional_requirements|fact|consent),revision,scope (request|session),options optional, answered bool. Request-wide extra requirements apply to still-active candidates; identical request field question coalesces. No simultaneous mutable owner identity in a TUI: each app has one owner.
Event keys: seq,timestamp,type,session_id (nullable),peer_id (nullable),summary,payload; every TUI reads only its runtime events.

Local HTTP: GET /health (public minimal); GET /owner/state, POST /owner/requests {text,requirements?}, POST /owner/answers {question_id,text,remember?,expected_revision?}, POST /owner/approvals {session_id,approve,proposal_digest?,expected_revision?}; owner routes require own bearer. Peer POST /messages is separately authenticated. A owns shape/validation of peer envelopes and shares message examples with B/root.

## Policy

DeterministicPolicy and ModelPolicy expose async extract(text:str,scenario:dict)->list[dict] and async decide(context:dict)->dict. Policy mode attribute deterministic or model. Policy.decide context keys: scenario,role (requester|provider),stage,requirements,own_facts,peer_facts,question/owner_answer if present,history (public only),memory (allowed own facts). Stage names must be agreed by A/B before use; no drift. Core calls policy for negotiation choices; it is not a dead unused adapter.

Decision schema: {action:ASK_OWNER|ASK_PEER|PROPOSE|ACCEPT|REJECT|WAIT,summary:str,field:str|null,question:str|null,facts:dict,terms:dict}. Defaults can fill empty objects/nulls in deterministic policy, but model output validated strict with no extra keys. Model never returns OWNER_APPROVAL. Facts used for declarations must have own-source evidence, not be invented; runtime rechecks model permissions and hard conditions. A/B agree responsibilities for deterministic next-step logic so B tests exercise the same adapter A invokes.

Model env: XAGENT_MODEL_BASE_URL (full API base, e.g. .../v1), XAGENT_MODEL_NAME, XAGENT_MODEL_API_KEY. No defaults naming an unverified live model. JSON mode with strict local schema validation; optional provider json_schema only if configured. 20s timeout, at most one repair; record usage metadata when available. No credentials available in this session so live model integration remains unverified until provided. No silent deterministic fallback in model mode.

## TUI

AgentApp(runtime) starts only its UI; CLI owns runtime.start/stop and Uvicorn lifecycle. Use Textual App.run_async, root supplies dependencies. Fixed identity header/profile, peer/session selector, scrollable public event log, highlighted questions/proposal/result and persistent Input. Bare input with selected pending question answers that question; otherwise starts request. Explicit /request, /answer <question-id> <text>, /approve <session-id>, /reject <session-id>, /sessions, /help commands may provide reliable keyboard controls. Approval carries displayed digest/revision. No arbitrary user text treated as approval. Selection must not let events steal input from another pending question.

Async events/polling must not block input. Set Rich markup=False for untrusted values. Headless Textual tests must exercise at least targeting and approval separation. Source docs: https://textual.textualize.io/guide/testing/ and https://textual.textualize.io/guide/workers/ .

## Final implementation additions

Snapshot also includes `memory` (own confirmed facts) and `blocked_messages` (message IDs). `retry_blocked_message(message_id)` is a synchronous owner action exposed through `POST /owner/retry {message_id}`; TUI `/retry MESSAGE_ID` invokes it. Processing errors persist as blocked inbox messages and require explicit retry; model mode never silently falls back. TUI `/remember QUESTION_ID TEXT` sets remember=True for personal facts only. `/approve` and `/reject` without an ID target the selected displayed session. Each owner may decide once per proposal; there is no approval withdrawal protocol.

Runtime supplies `allowed_actions` in each policy context. The model validates against the supported stage actions, in addition to the general Decision schema. This MVP implements field-based clarification/rejection/proposal flow; general free-text counteroffers and arbitrary peer questioning are deferred. Only public fields enter FILTER facts, and providers verify proposal facts against their own disclosed facts.
