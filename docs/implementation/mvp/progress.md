# MVP progress — plan docs/superpowers/plans/2026-10-16-decentralized-mvp.md

User explicitly requested implementation after reviewing decentralized four-process/TUI design. Earlier two-worker collaboration authorization persists. Work occurs in feat/deterministic-negotiation-workbench, preserving uncommitted milestone and research.

Ruling: continue in current feature checkout with disjoint ownership — a new worktree would omit uncommitted milestone files; review must inspect untracked files as well as diff.
Ruling: proceed with implementation plan as part of explicit MVP implementation request rather than another approval cycle — scope is now fixed by reviewed design and user's implementation instruction; local changes remain reversible.
Ruling: use A/B parallel ownership as previously requested, overriding sequential skill default — communication contract is frozen before dispatch; interface changes require coordination.
Ruling: use explicit HTTP JSON protocol behind adapter and defer standard A2A binding — user requests local interprocess HTTP, not a particular wire standard; no interoperability claim.
Ruling: model adapter implemented/tested against local fixtures, live provider check pending credentials — never pretend deterministic output is a model result.

| Tasks | Shared boundary | Preflight |
|---|---|---|
| A runtime / B policy | async extract and decide, context stages | contract agreed; exact stages coordinated before implementation |
| A runtime / B TUI | snapshot and owner actions | fixed identity; own DB; no independent UI state machine |
| A runtime / root CLI | lifecycle and FastAPI factory | root owns process launch; no shared SQLite |
| A schema / root fixtures | config and scenario dictionaries | A publishes example early; generic fields |
| A internal | transport ack vs business processing | inbox/outbox needed before ack; tests exercise restart |
| B internal | model action vs user consent | no approval action; explicit TUI controls |
| Root internal | verification vs claimed completion | real subprocess smoke required; live provider separate |

- [x] A core/transport
- [x] B policy/TUI
- [x] Root fixtures/launch/process acceptance
- [x] Cross review and final verification

## Final verification

Coordinator ran `uv run --group dev pytest -q` on the final frozen implementation: **55 passed, 1 upstream Starlette deprecation warning**, 22.65 seconds. Both standalone smoke commands passed for cofounder and venue. `git diff --check` passed. Actual PTY exercise verified Chinese input -> runtime request -> owner HTTP snapshot; Ctrl+Q exited with status 0. Independent reviewer re-ran the reported approval divergence, blocked-model-error and stale-question reproductions and confirmed the fixes.

Implementation is kept as local, reviewable changes on the existing feature checkout; no commit, push or merge was requested or performed. No integration decision is required for this local MVP delivery. Older research and milestone files were preserved.

See [usage and demo](README.md), [acceptance](acceptance.md), [backend](backend.md), and [policy/TUI](frontend.md). Live provider verification remains pending actual configuration/credentials. General free-text counteroffers and cross-request preference memory remain outside this MVP; explicit confirmed own facts are persisted and reused.
