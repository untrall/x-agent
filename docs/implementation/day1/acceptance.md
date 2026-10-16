# Day 1 integration acceptance

Scope: deterministic local prototype and interactive sample-backed UI. Not yet a live model or interoperable A2A service.

- [x] One documented command serves new workbench.
- [x] Sample mode works independently and is visibly marked.
- [x] Profile shows synthetic source and hard/ask conditions.
- [x] Candidate with 2 hours fails the 15-hour hard requirement.
- [x] Starting agent-b session pauses with a question for owner-a.
- [x] User can accept delay, add AI experience condition, or decline.
- [x] Answer continues same session with observable revision/profile version changes.
- [x] Answer changes session overlay only; original profile unchanged.
- [x] Backend survives process restart with session/question persisted.
- [x] Duplicate answer does not duplicate events; modified reused message conflicts.
- [x] Wrong owner and stale revision rejected and visible.
- [x] One approval never produces connection; two matching approvals do.
- [x] Decline never exposes contact details.
- [x] Refresh preserves session; API failure never substitutes fake success.
- [x] Desktop and narrow viewport controls remain usable.
- [x] New backend tests pass; original demo build remains unaffected.

## Evidence and limits

- `uv run --group dev pytest -q`: 10 passed, one upstream Starlette/httpx deprecation warning. Tests cover ownership, strict inputs, revision conflicts, idempotency, paused database reconstruction, and approval gating. Live process restart was additionally observed at the completed state.
- `uv run python scripts/smoke.py`: HTTP flow reaches CONNECTED and retrieves artifact. `python3 scripts/build_demo_data.py`: existing demo build succeeds.
- A/B cross-review and root browser observations are recorded in progress.md. UI stale-conflict recovery and network-error handling were inspected in source; fault injection for dropped responses was not performed. Backend stale/duplicate behavior is tested.
- Browser verification used the in-app browser with keyboard/semantic actions; pointer automation was inconsistent in the coordinator tab. This is not a claim of complete mobile/touch or cross-browser testing. Desktop and narrow screenshots/layout were inspected; no narrow horizontal overflow was observed.
- Sample mode was served separately as static files by B. No silent API-to-fixture fallback exists in the transport. Offline API failure was inspected in code rather than injected in the final browser run.
- Screenshot: workbench.png. Startup and usage: repository README Day 1 section. Agent reports: backend.md and frontend.md.
- Deferred: independent A2A agent services, live model policy, editable/general scenario schemas, real authentication, streaming and deployment. Synthetic roles and a fixed cofounder policy are intentional bounds of this phase.
