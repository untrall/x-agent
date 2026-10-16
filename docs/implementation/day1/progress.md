# Implementation ledger — day 1 deterministic milestone

Plan: docs/research/2026-10-16/plan.md. User explicitly authorized two collaborating subagents A/B and the first deterministic/backend plus sample UI stage.
Base commit: 6c7730d. Branch: feat/deterministic-negotiation-workbench.

Ruling: use current checkout on a new feature branch with disjoint A/B file ownership. Tracked base is clean; preserve pre-existing untracked research. This keeps the requested current target repo and immediate shared-contract collaboration; accidental file overlap would require coordination/rework.
Ruling: user specifically requests two concurrent implementers; use A/B in parallel, overriding skill's sequential-agent default. No nested agents. Cross-review by A/B followed by coordinator verification; no extra agent required.
Ruling: this milestone uses deterministic synthetic policy; LLM and external A2A are not acceptance requirements yet. UI must disclose mode. Core interface remains suitable for subsequent transport integration.

| Task/interface | Produces / consumes | Preflight |
|---|---|---|
| A backend | Session/Question/Event + API | Aligns deterministic pause/resume request; optional approvals become mandatory if UI exposes them |
| B UI | fixture + API adapter consumes same shapes | Works independently before API available; never silently fall back |
| A ↔ B | contract.md API and response fields | A owns schemas, B owns fixture; changes sent to coordinator and peer |
| A files ↔ B files | src/scripts/pyproject vs web | No file overlap; root docs coordinated by parent |

- [x] A implementation/tests
- [x] B implementation/interaction checks
- [x] A/B cross review
- [x] Coordinator end-to-end and visual verification

## Progress

- A started: exact initial response agreed (WAITING_INPUT, revision 2; require_ai_experience answer resumes same session and reaches PENDING_APPROVAL). SQLite state machine chosen for first deterministic phase.
- B started: vanilla browser workspace, fixture and explicit API adapters; bearer demo identities and public event summary agreed with A.
- Coordinator baseline: existing scripts/build_demo_data.py succeeds; original tracked product files unchanged. Existing generated demo data stays ignored.
- Coordinator review targets: no sample/API silent fallback; refresh never starts a second session; cross-owner and old revision failures are visible; approval remains separate from accepting a timing change.

## Completed handoff — 2026-10-16

A delivered FastAPI + SQLite deterministic negotiation and 10 passing backend tests. B delivered the profile/workbench/question UI with separate fixture/API transports. Both reviewed each other's contract boundaries. Review fixes include candidate-C participant authorization, clearing unauthorized cached UI on role change, owner-a-only starts, preserving pending mutation message IDs, and fixture revision/terms parity.

Coordinator independently ran the full backend suite, live HTTP smoke, and legacy demo-data build. Browser API flow preserved session `3af68eeb-ae23-4813-99cc-b1295af963ea` through r2 pause → r3 conditional answer (owner-a v2) → r4 single approval → r5 dual approval and result. Reload and a real server stop/start recovered the result. Candidate-C rejection followed by owner-b switch displayed an authorization error and cleared the old session. Sample decline preserved profile v1; sample accept resumed to approval. Desktop and narrow layouts were inspected; the narrow DOM viewport measured 504 CSS pixels without horizontal overflow. Keyboard controls completed the tested flow. IAB pointer clicks were inconsistent in the coordinator tab; B independently reported successful pointer use, so full cross-browser mouse/mobile-touch coverage remains unverified.

Server left running on 127.0.0.1:8000; stop it with Ctrl-C in its terminal, or restart using `uv run python scripts/dev.py`. No commits, pushes, publication, LLM calls, or remote A2A exchange were performed. This completes the requested initial deterministic milestone, not the whole tomorrow delivery plan.
