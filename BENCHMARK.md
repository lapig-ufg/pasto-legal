# Pasto Legal — Single-Agent Benchmark

Benchmark suite for the **single-agent architecture** introduced in
`refac/pi-sdk-develop`. The goal is to answer two questions as the agent's
tool registry grows:

1. **Quality** — Does the agent keep calling the *correct* tools, retrieving
   the *correct* skills, and completing multi-step confirm flows as the
   number of tools increases?
2. **Cost** — Does the agent get cheaper or more expensive than the previous
   multi-agent system as runs get longer, the context window grows, and all
   tool logic is loaded at once?

This document describes the benchmark **architecture and methodology** only.
The individual mocked tools live in `agent/tools/benchmark.py` and are wired
through `agent/extensions/pasto-legal-tools.js` and `agent/registry.py`.

---

## 1. Architecture under test

The `refac/pi-sdk-develop` branch replaced the previous multi-agent system
with a single LLM backed by a **Tool-RAG** router. The pipeline for one user
turn is:

```
User message
   │
   ▼
/chat  (api/main.py)
   │
   ├── (onboarding gate) ── terms not accepted ──► build_onboarding_prompt
   │                                                  (only accept_terms tool)
   │
   ▼
Tool-RAG  (agent/tool_rag.py)
   │  FAISS index over TOOLS (agent/registry.py)
   │  cosine similarity, top_k=5, min_similarity=0.3
   │  + ALWAYS_AVAILABLE tools appended unconditionally
   ▼
build_prompt  (agent/pi_rpc.py)
   │  injects ONLY the RAG-selected tool descriptions
   │  + skill instructions for tools that have them
   │  + <session-state> (user_id, properties, feedback_mode, ...)
   ▼
pi --mode rpc  (one subprocess per user, native JSONL session on disk)
   │  system prompt = AGENTS.md
   │  loads extensions/pasto-legal-tools.js (ALL tools registered via pi.registerTool)
   │
   ▼
LLM picks a tool ──► JS execute() ──► callTool("backend", {action, ...})
   │                                          via HTTP POST
   ▼                                              │
/tool  (api/main.py) ◄─────────────────────────────┘
   │  runs agent/tools/<backend>.py  with base64-json args
   │  dispatches by `action` via the module's ACTIONS dict
   ▼
JSON result ──► makeResult() ──► pi ──► LLM ──► user reply
```

### Key single-agent traits (vs. the old multi-agent system)

- **One LLM handles everything.** No router agent, no specialist sub-agents.
  The single model reads `AGENTS.md`, the RAG-selected tool list, and the
  session state, then decides which tool(s) to call.
- **Tool-RAG keeps the prompt lean.** Only ~5 tool descriptions are injected
  per turn, regardless of how many tools exist in the registry. This is the
  core hypothesis for cost control at scale.
- **All tools are always loaded in the JS extension** (`pi.registerTool`),
  but only the RAG-selected ones are *suggested* to the LLM in the prompt.
- **Skills are conditionally injected.** `build_prompt` only adds a tool's
  `skill` block if that tool is in the RAG-selected set — so longer skill
  docs do not bloat every prompt.
- **Per-run metrics are already logged.** `pi_rpc.py:_log_run_metrics`
  reads the `usage` block from pi's session JSONL on every turn and emits
  `run_metrics` log lines with tokens, cost, latency, and tool-call count.
- **Native session persistence.** pi writes its own JSONL on disk; there is
  no Valkey mirror of the conversation. Valkey is only used for tool session
  state (e.g. pending property registration, pending alert).

### Where the growth axis lives

The single variable we manipulate is **the number of tools in the registry**.
Tool count affects three places:

1. **Tool-RAG FAISS index** — more tools = larger index, more embeddings to
   build once at startup. Retrieval time is O(n) on `IndexFlatIP` but still
   trivial at these scales; the real question is whether *precision/recall*
   of the top-5 degrades as similar-named tools compete.
2. **`build_prompt` output** — the *number* of tools in the prompt is bounded
   by `top_k=5`, but the *content* of each suggested tool's `skill` can grow.
   The hypothesis is that prompt size stays roughly flat as the registry
   grows, because only 5 tools are ever injected.
3. **pi extension JS** — all tools are registered in
   `pasto-legal-tools.js` regardless of RAG. This file is loaded once per pi
   process; its size is a fixed cost per session, not per turn.

Everything else (model, provider, system prompt, session mechanics) is held
constant across benchmark runs.

---

## 2. Hypotheses

### H1 — Quality stays stable as the agent grows
Tool-RAG retrieves the correct top-5 tools regardless of registry size, and
the LLM still calls the right tool (and the right confirm step) out of the
suggested set. Measured by: **RAG precision/recall vs. gold tool set**,
**correct-tool-call rate**, **confirm-flow completion rate**.

### H2 — Cost stays roughly flat as the agent grows
Because Tool-RAG caps injected tools at `top_k=5`, prompt size (and thus
input tokens) should not grow with the registry. Counter-hypothesis: even
with a fixed top-k, (a) longer sessions accumulate context in pi's JSONL and
inflate input/cache tokens over time, (b) similar-named tools force the LLM
to reason more (more reasoning tokens, more turns), and (c) the always-loaded
JS extension grows the per-session footprint. Measured by: **input_tokens**,
**output_tokens**, **cache_read_tokens**, **cache_write_tokens**,
**cost_total**, **prompt chars**, **latency (elapsed_s)**.

### H3 — The confirm flow is the hardest quality signal
The two-step `request_*` → `confirm_*` pattern (mirroring
`request_feedback`/`save_feedback` and property registration) requires the
LLM to (a) call the right `request_*`, (b) wait for user confirmation, and
(c) call the matching `confirm_*` on "sim". With per-type confirm tools (8
tools instead of 5), the LLM must pick the *correct* confirm tool — a
non-trivial retrieval task that grows harder as more alert types exist.

---

## 3. Growth-simulation strategy

We simulate growth by adding **mocked tools** to the registry. Mocked tools
have real-looking descriptions and parameters but always return canned JSON
(no backend, no database, no WhatsApp). They are indistinguishable from real
tools from the LLM's perspective, so they exercise Tool-RAG retrieval, prompt
injection, and the LLM's tool-selection logic exactly as real tools would.

### Benchmark scale points

| Scale | Total tools | Added vs. baseline | Step |
|-------|-------------|--------------------|------|
| 1     | ~20         | 0                  | Baseline (current `refac/pi-sdk-develop`) |
| 2     | ~28         | +8                 | Alert tools (`agent/tools/benchmark.py`) — **this step** |
| 3     | ~60         | +~32               | Future filler batches (varied categories/descriptions) |
| 4     | ~120        | +~60               | Future filler batches |

The **current step** adds the 8 alert tools (4 alert types × {request,
confirm}) bringing the registry from ~20 to ~28. This is the first scale
point above baseline. Filler batches for scales 3 and 4 will be added in
later steps; the benchmark harness is designed so they slot in without
changing the test corpus or metric collection.

### Why per-type confirm pairs (8 tools, not 5)

Each alert type gets its own `request_*` and `confirm_*` tool. This doubles
the tool count vs. a generic `confirm_alert` and forces the LLM to retrieve
the *matching* confirm tool — directly exercising the "does it call the
right tool?" quality question. More tools per concept = harder retrieval =
better growth signal.

### Mocked tool contract

Mocked tools follow the exact same contract as real tools:

- Registered in `agent/extensions/pasto-legal-tools.js` via `pi.registerTool`
  with `name`, `label`, `description`, `parameters` (Typebox schema), and an
  `execute` that calls `callTool("benchmark", { action, ... })`.
- Indexed in `agent/registry.py` `TOOLS` with `name`, `description`,
  `category`, and (for `request_*`) a `skill` block.
- Mapped in `agent/registry.py` `ACTION_MAP` for the `/tool` dispatcher.
- Implemented in `agent/tools/benchmark.py` as classes with `request`/
  `confirm` static methods and an `ACTIONS` dict + `__main__` CLI entry
  identical to `feedback.py`/`property.py`.
- Session state persisted in Valkey under `session:{user_id}`, mirroring
  `property.py`'s pending-registration pattern (`pending_alert` key).

So a mocked tool is **observable at every layer**: Tool-RAG retrieval,
prompt injection, LLM tool-call, JS extension dispatch, `/tool` endpoint,
and Python action handler. The only thing that is fake is the return value.

---

## 4. Metrics

All metrics come from existing instrumentation — no new logging code is
required for this step.

### Quality metrics

| Metric | Source | What it tells us |
|--------|--------|------------------|
| RAG precision@5 | `tool_rag.search_tools` result vs. gold tool set | Did Tool-RAG surface the correct tool(s) in the top-5? |
| RAG recall@5 | same | Did Tool-RAG miss any gold tool? |
| Correct-tool-call rate | pi `tool_execution_start`/`_end` events vs. gold action | Did the LLM call the right tool? |
| Confirm-flow completion rate | sequence of `request_*` → user "sim" → `confirm_*` | Did the two-step flow complete? |
| Wrong-confirm-tool rate | `confirm_*` call type vs. pending `pending_alert.type` | Did the LLM call a mismatched confirm tool? |
| Hallucinated-tool rate | tool calls whose name is not in the registry | Did the LLM invent a tool? |

### Cost metrics

All from `pi_rpc.py:_log_run_metrics` (emitted as `run_metrics` log lines,
also returned in the `/chat` response as `result["metrics"]`):

| Metric | What it tells us |
|--------|------------------|
| `input_tokens` | Prompt size seen by the model (should stay flat if RAG works) |
| `output_tokens` | Reply length |
| `reasoning_tokens` | Model "thinking" — may rise with harder retrieval |
| `cache_read_tokens` / `cache_write_tokens` | Context-window reuse efficiency |
| `total_tokens` | Sum — the headline cost number |
| `cost_total` / `cost_input` / `cost_output` | $ cost per run |
| `elapsed_s` | Latency |
| `n_tool_calls` | How many tool calls the run made (proxy for complexity) |
| prompt chars | `build_prompt` output length (log it separately) |

---

## 5. Test corpus

A fixed set of prompts run against each scale point, so results are directly
comparable across registry sizes. The corpus is **not** included in this
step; it will be added alongside the filler batches. The shape is:

- **Positive — biomass alert**: "Me avisa no WhatsApp quando a biomassa passar de 2500 kg/ha" → gold: `request_biomass_alert`, then `confirm_biomass_alert`.
- **Positive — rain alert**: "Quero um alerta de chuva: se bater 80 mm numa semana me avisa" → gold: `request_rain_alert`, then `confirm_rain_alert`.
- **Positive — vigor alert**: "Avisa se o NDVI cair abaixo de 0.4" → gold: `request_vigor_alert`, then `confirm_vigor_alert`.
- **Positive — stocking rate**: "Me alerta se a lotação passar de 2.5 UA/ha" → gold: `request_stocking_rate_alert`, then `confirm_stocking_rate_alert`.
- **Negative — no alert**: "Qual a biomassa da minha fazenda?" → gold: `get_pasture_stats`, **no alert tool**.
- **Adversarial — similar wording**: "Me avisa quando a biomassa estiver boa" (vague threshold) → gold: `request_biomass_alert` with clarification, or refusal.
- **Adversarial — confirm mismatch**: user says "sim" after a biomass alert plan, but the corpus injects a pending rain alert → gold: `confirm_biomass_alert` (must match pending, not the latest request).

Each prompt is run with a fresh session and also as a continuation (to test
session-length effects). The "sim" confirmation is always a separate turn.

---

## 6. How to run

### Prerequisites

- The Pasto Legal stack running (`api.main:app` on `:3000`, Valkey on `:6379`,
  pi available on `PATH` with the `pasto-legal-tools.js` extension).
- `BENCHMARK.md` (this file) and `agent/tools/benchmark.py` present.
- `agent/registry.py` and `agent/extensions/pasto-legal-tools.js` updated
  with the alert tools.

### Steps

1. **Start the stack** (e.g. `docker compose up` or local dev mode).
2. **Reset the Tool-RAG index**: the FAISS index is built lazily on first
   `search_tools` call and cached in-process; restart the API after any
   registry change so the new tools are embedded.
3. **Send a prompt** via the `/chat` endpoint (or the Streamlit debug UI):
   ```
   POST /chat
   { "user_id": "bench-1", "message": "Me avisa no WhatsApp quando a biomassa passar de 2500 kg/ha", "session_state": {"terms_accepted": true} }
   ```
4. **Read the metrics** from the response (`result["metrics"]`) or the
   `run_metrics` log lines.
5. **Send the confirmation** as a second turn:
   ```
   POST /chat
   { "user_id": "bench-1", "message": "sim", "session_state": {...from step 3...} }
   ```
6. **Repeat** for each corpus prompt and each scale point.
7. **Aggregate** the metrics across runs and compare scale points.

### Direct tool sanity check (no LLM)

The mocked Python tools can be exercised directly, bypassing the LLM, to
verify the action handler end-to-end:
```bash
# request a biomass alert
python agent/tools/benchmark.py "$(python -c \
  "import base64,json; print(base64.b64encode(json.dumps(
    {'action':'request_biomass_alert','user_id':'bench-1',
     'operator':'gt','threshold':2500,'car_codes':['GO-1234567-X']}
  ).encode()).decode())")"

# confirm it
python agent/tools/benchmark.py "$(python -c \
  "import base64,json; print(base64.b64encode(json.dumps(
    {'action':'confirm_biomass_alert','user_id':'bench-1'}
  ).encode()).decode())")"
```
This requires Valkey running (the tools persist `pending_alert` in
`session:{user_id}`).

---

## 7. Decisions log

- **Per-type confirm pairs (8 tools, not 5).** Each alert type has its own
  `confirm_*` tool. More tools = harder retrieval = better growth signal,
  and it directly tests the "does the LLM call the *matching* confirm
  tool?" question.
- **Session-state pending-alert pattern.** `request_*` stashes a
  `pending_alert` dict in Valkey under `session:{user_id}`; `confirm_*`
  reads, clears, and echoes it. Mirrors `property.py`'s pending-registration
  pattern so the existing JS `makeResult`/`sessionState` plumbing works
  unchanged.
- **Mocked returns.** Tools return canned JSON (`{"message": ...,
  "session_state": ...}`) without hitting any backend. This isolates the
  benchmark to agent behavior (retrieval, selection, confirm flow) and
  removes backend variance from cost/quality numbers.
- **`registry.py` updates required.** The new tools are added to `TOOLS`
  (so Tool-RAG indexes them and `build_prompt` can inject their skills) and
  to `ACTION_MAP` (for `/tool` dispatch consistency). Without the `TOOLS`
  entry the tools are invisible to Tool-RAG and would never be suggested to
  the LLM — the benchmark could not run.
- **Alerts are NOT in `ALWAYS_AVAILABLE`.** They must go through RAG
  selection so we can measure retrieval quality. Only `generate_speech`,
  `consult_update_notes`, `request_feedback`, and `save_feedback` bypass RAG.
- **`category: "alert"`** for all 8 tools, grouping them in the registry
  without affecting RAG (categories are descriptive only; RAG uses the
  `name: description` embedding).
- **All logic operators available** for biomass (and reusable by any
  threshold alert): `gt`, `lt`, `le`, `ge`, `eq`, `neq`. This forces the
  LLM to map natural-language phrasing ("maior que", "no mínimo", "igual a")
  to the right operator — a non-trivial selection task worth benchmarking.
- **Vigor default operator `lt`, stocking-rate default `gt`.** Domain
  convention (NDVI drops = degradation; UA/ha exceeds = overstocking), but
  kept as explicit parameters so the LLM must still choose them.
- **No documentation of individual tools here.** Per the task scope, this
  file documents only the benchmark architecture and methodology. Tool
  semantics live in `agent/tools/benchmark.py` (docstrings) and
  `agent/registry.py` (skill blocks).

---

## 8. Tool taxonomy (categories in the registry)

| Category | Tools | Origin |
|----------|-------|--------|
| `property` | register/remove/rename property | Production |
| `analysis` | pasture/topographic stats, image generation, UA calculator | Production |
| `utility` | `generate_speech`, `consult_update_notes` | Production |
| `onboarding` | `accept_terms_and_conditions` | Production |
| `feedback` | `request_feedback`, `save_feedback` | Production |
| `alert` | `request_*_alert`, `confirm_*_alert` (biomass, rain, vigor, stocking rate) | **Benchmark (mocked)** |

Future filler batches (scales 3–4) will introduce additional mocked
categories to keep descriptions diverse and stress Tool-RAG's ability to
disambiguate.