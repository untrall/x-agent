# Decentralized MVP backend

The backend runs one `AgentRuntime` per process. Each runtime owns its SQLite database, peer list, owner credential, scenario, profile, inbox and outbox. The same `create_peer_app(runtime)` serves owner commands and authenticated peer messages. The HTTP listener and TUI share this runtime; no database or in-memory state is shared between processes.

## Public facade and wire protocol

`AgentRuntime(config, policy=None)` exposes `start()`, `stop()`, synchronous `snapshot()`, and async `broadcast(text, requirements=None)`, `answer(question_id, text, remember=False, expected_revision=None)`, and `approve(session_id, approve, proposal_digest=None, expected_revision=None)`. Broadcast returns `{request_id, session_ids, snapshot}`; answer and approve return the updated snapshot. Snapshot includes `agent`, `mode`, `requests`, `sessions`, `questions`, `events`, `memory`, blocked message IDs, and queue metrics.

Config requires `owner_token` distinct from the agent's peer `token` and every configured peer token. Owner routes use `owner_token`; `/messages` verifies the sender against the configured peer token, recipient, and session binding. Tokens are synthetic local-demo credentials. Only loopback peer URLs should be configured.

An X-Agent peer envelope has `schema_version`, `message_id`, `request_id`, `session_id`, `sender_agent_id`, `recipient_agent_id`, `type`, `causation_id`, and `payload`. Supported types are `REQUEST`, `FILTER`, `REQUIREMENTS`, `PROPOSAL`, `ACCEPT`, `REJECT`, and `APPROVAL`. HTTP 200 acknowledges durable inbox storage only. A background worker processes each pair in order and different pairs concurrently. Outbound messages enter the durable outbox before delivery; network failures retry. Repeated message IDs receive an idempotent acknowledgement and do not repeat a transition.

## Negotiation behavior

The scenario's typed fields and requirement operators drive screening. A provider evaluates its actual local profile and confirmed owner facts; a missing field yields `UNKNOWN`, never a pass. An initial hard failure becomes `NO_MATCH` without calling policy. A successful initial screen sends a `FILTER` response; after the requester answers a configured request-wide followup, active pairs receive revised requirements. A provider with an unknown required fact persists a session-scoped owner question and resumes the same pair after the answer. The same request-wide followup field coalesces across candidates. A revised requirement reuses an existing matching owner question or supersedes it.

Policy is called at decision points with local facts, hard-evaluation evidence, and the stage's `allowed_actions`. The runtime validates the exact decision schema, public fact evidence, and the prohibition on proposing or accepting a failed or unknown hard constraint. A valid policy `REJECT` ends the pair and sends a generic peer rejection; policy text stays local. Policy output cannot grant owner approval. The requester constructs a canonical proposal digest; the provider rechecks its current facts and confirms that the proposal's disclosed provider facts are unchanged before accepting. Both sides enter `PENDING_APPROVAL`. Each owner makes one explicit decision for that proposal digest; an approval cannot later turn into a rejection. Only two approvals produce the identical `CONNECTED` artifact. Rejection and `NO_MATCH` are terminal.

The profile's `public_fields` controls peer fact disclosure. `remember=True` stores a confirmed own fact in local memory; it does not automatically broadcast that memory. Events expose local summaries, field statuses and protocol decisions, without peer private profile notes.

## Verification and limits

Run `uv run pytest -q tests/test_mvp_core.py tests/test_mvp_http.py tests/test_mvp_processes.py` for rule evaluation, persistence/restart, pair identity and owner authorization, concurrent pair processing, stale approvals, and real four-process exchange. The existing day-one suite remains in the full `uv run pytest -q` run.

The protocol and bearer credentials are local demo mechanisms, not standard A2A or production authentication. The MVP negotiates configured fields and one canonical proposal; arbitrary free-form peer chat and counterproposals are not implemented. Live model-provider behavior requires credentials and remains unverified here. A policy or message processing failure becomes a visible `PROCESSING_ERROR` and a blocked inbox item; it does not invoke the model again automatically. The owner can inspect `blocked_messages` in `/owner/state` and POST `/owner/retry` with `{ "message_id": "..." }` after correcting the cause. This implementation does not yet enforce the optional per-session decision/question budget proposed in the design spec.
