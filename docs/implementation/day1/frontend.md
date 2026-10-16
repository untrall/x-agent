# Day-one frontend workbench

The vanilla HTML/CSS/JS workbench lives in `web/`. It shows Chinese public profile previews, candidate eligibility, both agents' public negotiation events, a real single-choice question form, session/version indicators, approval by each synthetic participant, and the approved result. It deliberately labels self-reported experience and the deterministic synthetic mode; it does not display a compatibility percentage.

## Run

From the repository root:

```sh
uv run python scripts/dev.py --port 8000
```

Open `http://127.0.0.1:8000/?mode=sample` for the self-contained local fixture or `http://127.0.0.1:8000/?mode=api` for the live local HTTP contract. The default URL opens sample mode. The top selector switches modes explicitly. API mode never falls back to fixtures when its server is unavailable. The synthetic role switch chooses the demo Bearer identity; it is not a production sign-in.

To run only the fixture with no backend process, use `python3 -m http.server 8080 --directory web` and open `http://127.0.0.1:8080/?mode=sample`.

The sample transport loads `web/fixtures/demo.json`, keeps the current sample session in localStorage, and implements the same pause/answer/approval states as the API. Each mode stores its session ID separately; refreshing resumes that session instead of creating another. “开始新会话” explicitly releases the current view and enables a new start. Sample records are local browser data.

## Checks performed

- `node --check web/app.js` passed.
- `python3 -m json.tool web/fixtures/demo.json >/dev/null` passed.
- Served the app on `127.0.0.1:8001` with `uv run python scripts/dev.py --port 8001 --db .local/frontend-check.sqlite3`.
- In the in-app browser, sample mode completed start → conditional answer → pending approval → owner-a approval → synthetic owner-b switch → second approval → CONNECTED result. Reload preserved the same session, revision 5, and result.
- In sample mode, candidate C reached NO_MATCH with a visible 2-hour versus 15-hour hard requirement reason.
- On the same server, explicit API mode loaded `/api/demo`, POSTed `/api/sessions`, and displayed WAITING_INPUT revision 2 with the backend event timeline and question options.

## Boundaries

This is a deterministic local prototype. It does not call an LLM, perform live A2A exchange, verify résumé claims, contact people, or release contact data. A conditional answer updates only the current session's owner-a profile version; final connection still requires both owners to approve the same proposal. The `message_id` of a pending API mutation is retained across an uncertain response so retry uses the backend's idempotency key. If an existing session mutation conflicts or loses its response, the UI reloads the server's current session before continuing.
