# Decentralized TUI MVP Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox syntax. The user explicitly requested implementation of the reviewed four-process TUI design; proceed through reversible local implementation and verification without another permission cycle.

**Goal:** Four identical local Agent applications communicate over HTTP, filter real profile facts, negotiate pairwise, ask their own owners for missing input, resume, and exchange approvals to produce a shared result.

**Architecture:** Each process owns its SQLite database, policy, inbox/outbox, peer configuration and Textual UI. No central coordinator. A's runtime provides a stable local interface used by B's TUI; headless and TUI modes execute the same runtime. JSON messages over loopback HTTP are explicitly X-Agent protocol, not standard A2A.

**Tech Stack:** Python 3.12+, existing FastAPI/Uvicorn, httpx, Pydantic, SQLite, Textual, pytest. Root owns dependency edits and lockfile.

**Spec:** ../specs/2026-10-16-multi-process-agent-design.md

## Global Constraints

- Existing day-one code and user research remain intact. Add MVP modules under src/xagent/mvp/; do not stage, commit, push or switch branches from workers.
- Use current feature checkout; it contains the user's uncommitted first milestone and is the explicitly shared workspace.
- Same app/config schema for all agents; no branch on agent-2/3/4 or cofounder/venue to select business outcome.
- Ports 8011–8014 by default, each binds loopback and uses a separate database. Tests use temporary ports/databases.
- Exact wire/local integration contract lives in docs/implementation/mvp/contract.md. Communicate changes to peer and root before adopting them.
- Profile facts must actually drive pass/fail/unknown; unknown never silently passes. No shared database or model context across peers.
- Persist inbox/outbox, sessions, questions and approvals; duplicate message IDs never repeat state transitions. Never hold HTTP waiting for an owner.
- Model and deterministic modes explicit. No credentials currently available; test provider behavior with local HTTP fixtures, report live-provider verification as pending.
- Owner approval is a separate user action, never a policy decision. A user's natural-language reply does not approve a proposal.
- Workers must not spawn agents. A and B work in disjoint files and cross-review; root independently validates and requests final read-only review.

## Review Focus

1. Receiver crashes after HTTP ack: persisted inbox resumes without losing or duplicating business transitions (A tests).
2. Parallel candidate questions: answering one never writes facts to another agent; request-wide requirements are explicitly scoped (A/B tests).
3. Peer identity/session injection: authenticated sender must match known peer and pair membership; malformed messages do not poison worker loop (A tests).
4. Model invents facts or approvals: strict output schema and runtime checks prevent unauthorized mutation; timeout/invalid JSON visible (B/A tests).
5. Late messages or approval for stale terms: terminal state remains terminal and digest mismatch rejected (A tests).

## Task 1 Core runtime and HTTP transport — A

Files: src/xagent/mvp/{__init__,models,scenario,storage,runtime,server}.py, tests/test_mvp_core.py, tests/test_mvp_http.py. Own runtime-related tests only. Root handles launcher/config files; coordinate fixtures schema early.

Produces AgentRuntime(config, policy=None), start()/stop(), snapshot(), broadcast(text, requirements=None), answer(question_id,text,remember=False,expected_revision=None), approve(session_id,approve,proposal_digest=None,expected_revision=None), and create_peer_app(runtime). Exact contract below supplied as separate shared file.

- [x] Write and observe failing tests for real constraints, arbitrary agent IDs, unknown values and generic second scenario.
- [x] Implement generic schemas/config loading and actual rule evaluation with fail/pass/unknown reasons.
- [x] Write and observe failing tests for persisted message dedup, session binding, owner pause/resume and terminal/approval rules.
- [x] Implement transactional SQLite processing and outbox retries; process independent sessions concurrently while serializing one session.
- [x] Implement authenticated HTTP receive/health and local owner endpoints needed by smoke tests. HTTP ack means durable receipt, not business agreement.
- [x] Test restart while WAITING_INPUT and restart of pending inbox/outbox; ensure inactive peer doesn't block healthy peers.
- [x] Review B's integration surfaces; report scope and commands in docs/implementation/mvp/backend.md.

## Task 2 Policy and TUI — B

Files: src/xagent/mvp/{policy,tui}.py, tests/test_mvp_policy.py, tests/test_mvp_tui.py, docs/implementation/mvp/frontend.md. Do not edit A's modules or dependencies. Root handles CLI launcher and configs.

Consumes runtime and scenario contract. Produces DeterministicPolicy, ModelPolicy (HTTP chat-completions compatible), and AgentApp(runtime) with async run. Public methods asynchronous as shared contract specifies.

- [x] Write and observe failing tests for generic structured requirement extraction and Decision schema, unknown evidence and invalid model output.
- [x] Implement deterministic extraction from explicit field=value clauses plus scenario-provided aliases/patterns; disclose its limited natural-language coverage.
- [x] Implement model HTTP adapter using environment settings, JSON response format, strict local validation, timeout, one repair attempt, explicit errors and usage metadata. Never fall back silently.
- [x] Implement simple Textual header/profile, session list, live logs, question and proposal panel, input box and explicit approval/refusal controls. Input must not block incoming messages.
- [x] Write Textual run_test tests for submit demand, targeted answer, separate approval and event updates while typing; no private peer data.
- [x] Review A's contract compliance and record commands/limits in frontend.md.

## Task 3 Configuration, launch and real process acceptance — root

Files: pyproject.toml, uv.lock, configs/mvp/**, scripts/run_agent.py, scripts/smoke_mvp.py, tests/test_mvp_processes.py, README.md, docs/implementation/mvp/{progress,acceptance}.md.

- [x] Add dependencies and fixed resolved lockfile; preserve old tests.
- [x] Supply cofounder scenario and four configs: candidate 2 fails real hours condition; 3/4 pass, private/unknown experience requires their own owner response. Outcome derives from facts/answers.
- [x] Supply minimal venue scenario fixture using same schema/rules. No bespoke venue UI.
- [x] CLI starts selected config with same runtime, --headless for tests; TUI and HTTP run concurrently and shut down cleanly. Document four commands instead of imposing terminal software.
- [x] Real subprocess smoke: fan-out request → reject 2 → requester extra requirement → 3/4 owner questions → 3 qualifies and 4 rejects → approvals at both endpoints → matching artifacts. Persist evidence, no external publication.
- [x] Verify restart at paused state, repeat delivery and no wrong-owner approval; swap candidate answers and verify result follows facts.
- [x] Run old and new suite; inspect actual TUI via PTY or Textual test snapshots; receive final review and fix important issues.
- [x] Document exact completion and live-model limitation, controls, reset/restart and known issues. Keep local changes reviewable; no publishing.

Final implementation/verification record: `docs/implementation/mvp/acceptance.md` and `progress.md`. Full suite: 55 passed; live provider pending credentials.
