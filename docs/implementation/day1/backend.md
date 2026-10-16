# Day 1 backend: deterministic local negotiation

## Delivered

- FastAPI JSON API at the contract's seven routes: health, demo, session create/get, answer, approval, and approved artifact.
- Synthetic Chinese cofounder scenario with `owner-a` (林澈), `owner-b` (陈予), and an ineligible 2-hour candidate. AI product experience is explicitly `self-reported`.
- Explicit SQLite state machine: `READY → WAITING_INPUT → NEGOTIATING → PENDING_APPROVAL → CONNECTED`, with `NO_MATCH` and `DECLINED` terminal branches. The transient `NEGOTIATING` step is recorded as an event; the answer response is already `PENDING_APPROVAL`.
- Each session is a durable JSON snapshot in SQLite. Each mutation executes in `BEGIN IMMEDIATE` and writes the snapshot and idempotency response in one transaction. The `(owner_id, message_id)` key returns the original response for identical retries and rejects changed requests. Ownership is checked before idempotency; idempotency is checked before revision so a successful retry works after the revision advances.
- `Authorization: Bearer demo-owner-a` and `demo-owner-b` select synthetic owners. Only owner-a starts this scenario or answers its question. For agent-b sessions both owners may read; for rejected agent-c sessions only owner-a may read. Both owners must approve the same proposal digest before the artifact is available. Request bodies reject extra fields and wrong types, including a forged `owner_id`.
- `scripts/dev.py` binds `127.0.0.1:8000` by default, serves the `web/` directory on the same origin when present, and stores state at `.local/xagent.sqlite3` unless `--db` is supplied.

## Run and verify

```bash
uv run --group dev pytest -q
uv run python scripts/dev.py --db .local/xagent.sqlite3
# in another terminal:
uv run python scripts/smoke.py --mode deterministic
```

The backend suite reports **10 passed**. It emits one upstream `StarletteDeprecationWarning` concerning `httpx` and `starlette.testclient`; no test failures. The live smoke command completed pause → answer → two approvals → artifact using HTTP on port 8765, reporting 10 events. After stopping and starting a new server process against the same `/tmp/xagent-day1-live-smoke.sqlite3`, a GET by owner-b returned the existing session ID `2b27043e-22b1-4753-9287-5dfc63ea8759` in `CONNECTED` at revision 5 with 10 events. Automated tests also reopen the database while a session is paused, then answer through the new app instance, proving resumability before the owner responds.

## Scope and tradeoff

This bounded milestone uses a small explicit SQLite state machine instead of the researched LangGraph checkpoint path. Its transitions and atomic idempotency are straightforward to inspect and test for this fixed deterministic scenario. It does **not** call an LLM, run two independent agent processes, or implement network A2A; those remain later work. The bearer tokens are local synthetic role selectors, not production authentication. No verified resume claim or compatibility score is generated.

## Cross-review and contract check

The frontend review found and relayed five integration issues: owner-b could attempt the owner-a-only start call; retries used fresh message IDs and did not refresh on ambiguous or stale responses; the sample decline changed a profile version; the sample hard-reject metadata and terms differed from the API; and the requirement heading treated an `ask` as a hard rule. The frontend owner reports these are now corrected; coordinator is running final browser acceptance. The backend review found that owner-b could read an agent-c hard-rejection session, although owner-b was not a participant. A regression test first reproduced HTTP 200; the authorization check now returns 403 and the full backend suite passes.

Against the current shared contract, the persistent state machine covers: the public demo and health shapes; authenticated create/read; hard rejection; pending owner question; answer and same-ID resume; session-scoped profile version; conditional self-reported experience; revision and strict body checks; idempotent retries after restart; two separate approvals against one digest; terminal refusal; and artifact gating. All session, question, event, and terms keys required for this deterministic phase are emitted. The browser's sample mode remains a parallel frontend simulation; backend persistence applies to API mode.
