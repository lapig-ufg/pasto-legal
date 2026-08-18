# Pasto Legal — promptfoo agent tests

This folder contains a [promptfoo](https://www.promptfoo.dev) evaluation
suite for the **Pasto Legal** agent. Tests run against the live FastAPI
`POST /chat` endpoint — the agent (a `pi` coding-agent subprocess speaking
JSON-RPC, backed by Google Gemini) is treated as a black box.

The focus is **tool-selection / routing**: does the agent call the right
tool (or no tool) for a given user intent, in Brazilian Portuguese, with
WhatsApp-style formatting, without self-identifying as a bot, and without
inventing tools outside the registry.

## Layout

```
promptfoo/
├── package.json              # npm manifest (promptfoo + dotenv)
├── run.mjs                   # entrypoint — calls promptfoo.evaluate()
├── providers/
│   └── chat-provider.mjs     # custom ProviderFunction → POST /chat
├── data/
│   ├── tools-allowed.mjs      # canonical tool name allowlist
│   └── session-fixtures.mjs  # reusable session_state objects
├── cases/
│   ├── routing.mjs           # tool-routing cases (property, faq, smalltalk, ...)
│   └── feedback.mjs          # frustration → request_feedback → save_feedback
├── assertions.mjs            # shared JS assertion helpers
└── .env.example
```

## Prerequisites

1. **Node.js ≥ 22.22.0** (Node 24 LTS recommended).
2. The **Pasto Legal app running** locally. From the repo root:
   ```bash
   # Make sure GOOGLE_API_KEY (and GEE_* if running GEE tests) are in your env.
   uv run uvicorn api.main:app --port 3000
   ```
   The provider POSTs to `http://localhost:3000/chat` and resets sessions
   via `POST /reset`.
3. `GOOGLE_API_KEY` in the environment (read by the pi subprocess the app
   spawns). Copy `promptfoo/.env.example` → `promptfoo/.env` and fill it in.

## Running

```bash
cd promptfoo
cp .env.example .env          # then edit .env
npm install
npm test
```

`npm test` runs `node run.mjs`, which:
- loads `.env`,
- assembles all test cases,
- calls `promptfoo.evaluate(suite, { maxConcurrency: 1 })`,
- prints a PASS/FAIL table and exits non-zero on any failure.

To open the promptfoo web viewer on the latest results:

```bash
npm run view
```

### Execution order

Tests run **sequentially** in array order (`maxConcurrency: 1`). Each test
uses a unique `user_id` (`promptfoo-<slug>`) and calls `POST /reset` first,
so tests are **isolated** — order doesn't matter for correctness, and a
failure in one test doesn't contaminate the next.

### Terms acceptance

No warmup is needed. The `/chat` endpoint only checks the DB for terms
acceptance when `session_state.terms_accepted` is falsy
(`api/main.py:200`). Tests that need the normal flow simply send
`terms_accepted: true` in `session_state` (see `REGISTERED_USER_SESSION`
and `AWAITING_FEEDBACK_SESSION` in `data/session-fixtures.mjs`), which
bypasses the onboarding gate directly.

## What's evaluated

Each test case sends one user message to `/chat` with a specific
`session_state` fixture (registered user or awaiting-feedback) and
asserts on the response:

- **Portuguese language** — heuristic pt-BR check (plus LLM-as-judge).
- **WhatsApp formatting** — `*bold*` allowed, no markdown headers / `**`.
- **No self-identification as bot** — no "IA / robô / chatbot / modelo".
- **Right tool called** — `result.tool_calls` (see *Step 6* below) is
  inspected for the expected tool name and arguments.
- **No hallucinated tools** — any called tool not in
  `data/tools-allowed.mjs` (mirror of `agent/registry.py`) fails the test.
- **Session state deltas** — e.g. `request_feedback` must set
  `feedback_mode="awaiting_rating"`.
- **Feedback remediation** — frustration triggers `request_feedback`;
  positive/negative replies trigger `save_feedback` with the matching
  `verdict`.
- **LLM-as-judge (optional)** — a separate Gemini model grades tone,
  clarity, identity, and formatting on every case. Disable by setting
  `JUDGE_MODEL=""` in `.env`.

## Optional Earth Engine tests

Cases that call real Earth Engine tools (`get_pasture_stats`,
`generate_property_image`, ...) are **opt-in** because they require GEE
credentials, a registered property, and are slow. Enable them with:

```bash
RUN_GEE_TESTS=1 npm test
```

## How tool calls are observed (Step 6)

The stock `/chat` response only exposed `metrics.n_tool_calls` (a count) and
session-state deltas. To make assertions on **which** tool ran and with
**what arguments**, this suite relies on a small additive change to
`agent/pi_rpc.py`:

- `PiRpcClient.prompt()` now tracks `tool_execution_start` events and
  populates `result["tool_calls"] = [{ name, args }, ...]`.
- `/chat` returns this list as-is, so the chat provider surfaces it under
  `context.providerResponse.metadata.toolCalls`.

If you revert that change, the `calledTool(...)` / `noHallucinatedTool()`
/ `save_feedback.verdict` assertions will stop working (they'll see an
empty tool list).

## Keeping the allowlist in sync

`data/tools-allowed.mjs` is a hand-maintained mirror of `agent/registry.py`'s
`TOOLS` list. When you add or rename a tool in the registry, update the
allowlist too — otherwise the no-hallucination assertion will flag the new
tool as a hallucination.

## Notes on determinism

Tests use the real `gemini-3.5-flash-lite` model and are therefore
non-deterministic. To reduce flakiness:

- Each test uses a unique `user_id` (`promptfoo-<slug>`) and calls
  `POST /reset` before `/chat`, so pi session history doesn't leak across
  tests.
- `maxConcurrency` defaults to 1 (serial) to avoid load-related variance.
- LLM-judge grading adds a second model call per test (extra latency and
  cost); disable with `JUDGE_MODEL=""` for deterministic-only runs.