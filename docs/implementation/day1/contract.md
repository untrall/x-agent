# Day 1 shared contract

User approved implementation with exactly two cooperating agents. Scope: deterministic negotiation pause/answer/resume and profile preview/workbench/question UI, initially sample data then local API integration. This is phase one; do not claim live LLM, standard A2A network or full planned hackathon product completed.

## Shared workspace and ownership

Work in /Users/MacBook/projects/2026_10_17_hackathon/x-agent, branch feat/deterministic-negotiation-workbench. Existing research docs are untracked and must be preserved. No git staging/commits, branch switching, worktree creation or deleting others' work from agents. Coordinator owns integration/review/docs. No nested subagents.

A owns src/xagent/**, pyproject.toml, uv.lock, tests/test_* backend tests, scripts/dev.py, scripts/smoke.py, docs/implementation/day1/backend.md.
B owns web/** (including web/fixtures/demo.json and fixture transport), tests/frontend/** if useful, docs/implementation/day1/frontend.md. Do not install a large frontend framework; vanilla HTML/CSS/JS suits this initial milestone. Existing core/, demo/, scenarios/, research docs remain unchanged.

Use Chinese UI. Synthetic cofounder scenario: owner-a (技术创始人 林澈) seeks product/business partner, >=15 hours/week hard requirement, joining date ask owner; owner-b (产品负责人 陈予) has self-reported AI product experience, 15 hours/week, full-time after 90 days, wants 14-day trial. Candidate agent-c offers 2h/week and is rejected by hard constraint. This is not a verified resume. No real credentials, LLM calls or remote publication.

## Stable HTTP contract v0

JSON uses snake_case. Errors {"error":{"code":"...","message":"..."}}. Local synthetic demo bearer tokens demo-owner-a, demo-owner-b resolve to owner-a/owner-b. Never trust body owner_id. UI may switch demo identity, clearly synthetic role switch, no production security claims. Bind server localhost by default.

GET /api/health -> {status:"ok",mode:"deterministic"}.
GET /api/demo -> {scenario:{id:"cofounder.v1",name:"创业合伙人"},profiles:[...],candidates:[...]}. Profiles contain owner_id,agent_id,name,role,summary,facts:[{field,label,value,source,visibility}],requirements:[{field,label,kind,operator,value}],version. candidates contain agent_id,name,role,summary,eligible:boolean,reason:string. A should publish a sample of this early for B and align fixture; details outside these keys can be added without breaking.
POST /api/sessions -> body {scenario_id:"cofounder.v1",candidate_agent_id:"agent-b",message_id:string}. Auth A required. Deterministic policy progresses to WAITING_INPUT; hard-fail candidate produces NO_MATCH.
GET /api/sessions/{session_id} -> Session; participants only.
POST /api/sessions/{session_id}/answers -> {question_id,answer:"accept_90_days"|"require_ai_experience"|"decline",expected_revision,message_id,scope:"session"}. Correct owner required. Identical message_id + same payload is idempotent; reused ID with different payload conflicts. Stale revision 409; wrong owner 403; invalid answer/shape 422. A decline ends NO_MATCH. Other answers add observable NEGOTIATING/resume events, preserve session ID, increment only A's session profile version and then reach PENDING_APPROVAL with a proposal. Global demo profile stays unchanged.
POST /api/sessions/{session_id}/approvals -> {proposal_digest,approve:boolean,expected_revision,message_id}. Participants only; each owner approves once against same digest; one approval keeps PENDING_APPROVAL, both -> CONNECTED; decline -> DECLINED. This small endpoint provides meaningful outcome after resume if feasible; mandatory once exposed by UI. No human approval implied by agent acceptance.
GET /api/sessions/{session_id}/artifact -> approved result only, otherwise 409. No contact data before both approve. Artifact has session_id,scenario_id,terms,consents,next_step and mode.

Session shape (all keys present, nullable as stated):
{session_id,scenario_id,candidate_agent_id,mode:"deterministic",state,revision:int,profile_versions:{"owner-a":int,"owner-b":int},rounds:int,terms:object,proposal:null|{version:int,digest:string,terms:object},pending_question:null|Question,approvals:[],events:Event[],artifact:null|object}.
Question {question_id,owner_id:"owner-a",field:"start_in_days",title,reason,options:[{value,label}],scope:"session",base_revision:int}.
Event {seq:int,session_id,timestamp:ISO,actor:"agent-a"|"agent-b"|"owner-a"|"owner-b"|"system",type,public_summary,payload:object,mode:"deterministic"}.
States READY,NEGOTIATING,WAITING_INPUT,PENDING_APPROVAL,CONNECTED,NO_MATCH,DECLINED,CANCELLED,ERROR; current phase need only relevant implemented states. Event types readable and consistent, A shares early.
Terms {start_in_days:90,hours_per_week:15,trial_days:14,requires_ai_experience:boolean,ai_product_experience:true}. Evidence marked self-reported. Do not fabricate numeric compatibility scores.

## Acceptance

A: meaningful tests for pause/resume same ID, SQLite reconstruction/restart recovery, owner authorization, answer invalid shape, stale revision, identical duplicate/reused ID mismatch, hard rejection, session-only profile update. If approval endpoints supplied test one/both approvals, wrong digest, duplicate, terminal rejection. Prefer LangGraph checkpoint already researched if straightforward; explicit small SQLite state machine acceptable for this deterministic milestone, record tradeoff. All claims match actual implementation.
B: polished readable responsive workspace with profile preview, both sides' public negotiation timeline, pending question options, explicit session-only scope, same session/version display after resume, reject branch, state/status indicators. Sample mode functions without backend, clearly marked. API mode is explicit, no silent fixture fallback. Refresh can resume saved session, no duplicate start. textContent/DOM construction for untrusted values, accessible controls and reduced-motion support. B can implement approval/result UI after core question flow.

Both send coordinator and peer a milestone update about every ~60 seconds while active: done, currently doing, blocked/next. Immediately communicate contract changes before implementing them. Coordinator consolidates user-facing updates and validates browser + backend end-to-end. Write reports in assigned docs paths with commands, results and limitations.
