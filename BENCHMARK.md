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
| 2     | ~28         | +8                 | Alert tools (`agent/tools/benchmark.py`) |
| 3     | ~41         | +9                 | Weather tools (`agent/tools/benchmark.py`) |
| 4     | ~49         | +8                 | Forage budget, paddock management, vaccination (`agent/tools/benchmark.py`) — **this step** |
| 5     | ~60         | +~11               | Future filler batches (varied categories/descriptions) |
| 6     | ~120        | +~60               | Future filler batches |

The **current step** adds 8 mocked tools across three new categories:
`pasture` (forage budget), `paddock` (paddock CRUD + per-paddock stats +
rotation scheduling), and `herd` (vaccination calendar), bringing the
registry from ~41 to ~49. These tools bridge pasture analysis, herd
management, and farm-level decision-making — they test whether the LLM
can disambiguate between property-level stats (`get_pasture_stats`) and
paddock-level stats (`get_paddock_pasture_stats`), and whether it can
chain multi-tool workflows (e.g. `auto_generate_paddocks` →
`get_rotation_schedule`). Four of the eight tools carry `skill` blocks
(forage budget, auto-generate, rotation, vaccination); the paddock stats
and label/delete tools are skill-less. Filler batches for scales 5 and 6
will be added in later steps; the benchmark harness is designed so they
slot in without changing the test corpus or metric collection.

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
- **Positive — rain forecast 15 days**: "Qual a previsão de chuva para os próximos 15 dias?" → gold: `get_rain_forecast_15_days`.
- **Positive — rain forecast months**: "Como vai ser a chuva nos próximos 2 meses?" → gold: `get_rain_forecast_months` (months=2).
- **Positive — rain history**: "Quanto choveu em março de 2024?" → gold: `get_rain_history` (month=3, year=2024).
- **Positive — weather today**: "Como está o tempo agora?" → gold: `get_weather_today`.
- **Adversarial — rain vs temperature**: "Qual a previsão do tempo para os próximos 15 dias?" (ambiguous: rain or temperature) → gold: `get_rain_forecast_15_days` or `get_temperature_forecast_15_days` with clarification.
- **Adversarial — drought vs rain**: "Me fala sobre a seca de outubro de 2024" → gold: `get_drought_index` (not `get_rain_history`).
- **Adversarial — soil moisture vs rain**: "Como está a umidade da terra?" → gold: `get_soil_moisture` (not `get_weather_today` or rain tools).
- **Positive — forage budget**: "Tenho 80 UA. Quantos dias de pasto ainda tenho?" → gold: `get_forage_budget` (herd_size_ua=80).
- **Adversarial — forage budget needs herd size**: "Quanto pasto me resta?" (no herd size given) → gold: LLM asks for herd size, then calls `get_forage_budget`.
- **Positive — auto-generate paddocks**: "Divide minha fazenda em 5 piquetes" → gold: `auto_generate_paddocks` (count=5).
- **Positive — rotation schedule**: "Qual piquete devo soltar o gado primeiro?" → gold: `get_rotation_schedule` (possibly preceded by `auto_generate_paddocks` if no paddocks exist).
- **Adversarial — paddock vs property stats**: "Qual a biomassa do Pasto 1?" → gold: `get_paddock_pasture_stats` (not `get_pasture_stats`).
- **Positive — vaccination calendar**: "Quando tenho que vacinar o gado?" → gold: `get_vaccination_calendar`.

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
- **Weather tools are skill-less read-only mocks (Step 3).** Unlike the
  alert tools (which carry `skill` blocks for the two-step confirm flow),
  the 9 weather tools have no skill — they are pure data-retrieval mocks.
  This intentionally tests whether the LLM calls them correctly based only
  on the `description` field, without step-by-step skill guidance. It also
  keeps prompt injection lean (no extra skill text) and makes the
  disambiguation task harder (the LLM must choose between similarly-named
  tools from description alone).
- **Shared 5-attribute rain-row shape.** `get_rain_forecast_15_days`,
  `get_rain_forecast_months`, `get_rain_history`, and `get_weather_today`
  all return rows with the same 5 attributes (date/month, precipitation_mm,
  precipitation_max_mm, precipitation_min_mm, probability_pct). This forces
  the LLM to distinguish them by tool name/description, not by output shape
  — a harder retrieval task than if each had a distinct schema.
- **`months` capped at 3 with validation.** `get_rain_forecast_months`
  validates `1 <= months <= 3` and returns an error otherwise, exercising
  parameter-validation logic (which the alert tools do not have).
- **`get_rain_history` rejects future dates.** Validates that the requested
  month/year is in the past, adding a temporal-correctness check that
  stresses the LLM's ability to pass valid parameters.
- **Deterministic mocked data.** Weather tools use a seed derived from the
  date string so repeated calls within a process return stable values.
  This makes benchmark results reproducible while still appearing
  realistic (Cerrado wet season Oct–Mar, dry season May–Sep).
- **`category: "weather"`** for all 9 tools, grouping them in the
  registry without affecting RAG (categories are descriptive only; RAG
  uses the `name: description` embedding). The category also serves as
  the deletion key — see the deletion guide in §8.
- **Three new categories for Step 4: `pasture`, `paddock`, `herd`.**
  Each is semantically distinct from production categories and from each
  other, aiding RAG disambiguation. `pasture` (forage budget) bridges
  analysis + herd; `paddock` groups CRUD + per-paddock stats + rotation;
  `herd` groups vaccination and future herd-health tools.
- **Paddock state mirrors property state.** Paddocks are stored in
  Valkey under `session:{user_id}` → `all_paddocks` (list of dicts with
  `id`, `label`, `area_ha`, `car_code`), mirroring the property
  `all_properties` pattern. CRUD tools (`auto_generate_paddocks`,
  `set_paddock_label`, `delete_paddock`) read/write this key and return
  `session_state` so the JS extension's `makeResult` plumbing works
  unchanged.
- **Per-paddock stats match real schema shapes.** `get_paddock_pasture_stats`
  returns a `PastureStats.model_dump()`-shaped dict (4 optional nested
  `*_stats` sections with `observation_year`, `amount: {value, unity}`,
  or `data: [{..., amount}]`); `get_paddock_topographic_stats` returns
  `{elevation: {value, unity}, slope: {value, unity}}`. Both also return
  `stats_text` (formatted Portuguese string) — the only field the LLM
  currently sees via `makeResult({message: result.stats_text})`.
- **No per-paddock image tools.** Per the decision to skip mocked image
  generation for paddocks, only the two stats tools were implemented
  (no `get_paddock_biomass_image`, etc.). This keeps the paddock tool
  count lean and avoids the complexity of generating mock base64 PNGs.
- **`set_paddock_label` merges set + update.** Instead of separate
  `set_paddock_label` and `update_paddock_label` tools (which would be
  semantically identical), a single tool handles both creating and
  renaming labels — identified by `paddock_id` only.
- **`get_forage_budget` requires `herd_size_ua`.** The tool returns an
  error if herd size is not provided. The skill instructs the LLM to
  ask the user for herd size before calling the tool — a parameter-
  gathering step that the alert tools do not exercise.
- **`get_rotation_schedule` auto-falls-back.** If no paddocks exist in
  session state, the tool mocks 4 default paddocks instead of erroring.
  This lets the benchmark test the tool in isolation (without a prior
  `auto_generate_paddocks` call), but the skill still recommends
  generating paddocks first for a realistic flow.
- **`get_vaccination_calendar` is Cerrado/Centro-Oeste focused.** The
  mocked calendar reflects LAPIG/UFG's regional focus (Goiás): Aftosa
  in May + November, Brucelose for females 3–8 months, annual Raiva/
  Carbúnculo/Clostridioses/Botulismo. The skill instructs the LLM to
  always caveat that it's a reference calendar and to consult a vet.

---

## 8. Tool taxonomy (categories in the registry)

| Category | Tools | Origin |
|----------|-------|--------|
| `property` | register/remove/rename property | Production |
| `analysis` | pasture/topographic stats, image generation, UA calculator | Production |
| `utility` | `generate_speech`, `consult_update_notes` | Production |
| `onboarding` | `accept_terms_and_conditions` | Production |
| `feedback` | `request_feedback`, `save_feedback` | Production |
| `alert` | `request_*_alert`, `confirm_*_alert` (biomass, rain, vigor, stocking rate), `list_schedulers`, `delete_scheduler` | **Benchmark (mocked)** |
| `weather` | `get_rain_forecast_15_days`, `get_rain_forecast_months`, `get_rain_history`, `get_weather_today`, `get_temperature_forecast_15_days`, `get_drought_index`, `get_evapotranspiration`, `get_soil_moisture`, `get_climate_summary` | **Benchmark (mocked)** |
| `pasture` | `get_forage_budget` | **Benchmark (mocked)** |
| `paddock` | `auto_generate_paddocks`, `set_paddock_label`, `delete_paddock`, `get_paddock_pasture_stats`, `get_paddock_topographic_stats`, `get_rotation_schedule` | **Benchmark (mocked)** |
| `herd` | `get_vaccination_calendar` | **Benchmark (mocked)** |

Future filler batches (scales 4–5) will introduce additional mocked
categories to keep descriptions diverse and stress Tool-RAG's ability to
disambiguate.

### Deletion guide — removing all benchmark mocked tools

All benchmark mocked tools are organized so they can be deleted in one
sweep per category when testing is finished. Each category is tagged with
a comment marker (`# weather-benchmark`, `# alert (benchmark — mocked)`,
`# pasture-benchmark`, `# paddock-benchmark`, `# herd-benchmark`) in the
source files.

**Weather tools (`category: "weather"`) — 9 tools, read-only:**
1. `agent/registry.py` — remove the 9 entries in `TOOLS` under the
   `# ═══ Weather (benchmark — mocked) ═══` section, and the 9 entries in
   `ACTION_MAP` under the `# benchmark (mocked weather data tools)` comment.
2. `agent/extensions/pasto-legal-tools.js` — remove the entire
   `// ── Weather (benchmark — mocked) ────────────────────────` block
   (9 `pi.registerTool` calls).
3. `agent/tools/benchmark.py` — remove the entire `# ── Weather tools
   (benchmark — mocked) ──` section (the `_rain_for_day`,
   `_rain_table_message` helpers and all 9 `get_*` functions) and their
   entries in the `ACTIONS` dict under `# weather-benchmark`.

**Alert tools (`category: "alert"`) — 10 tools, two-step confirm flow:**
1. `agent/registry.py` — remove the `# ═══ Alert Schedulers (benchmark
   — mocked) ═══` and `# ═══ Scheduler management (benchmark — mocked)
   ═══` sections in `TOOLS`, and the corresponding entries in
   `ACTION_MAP` under `# benchmark (mocked alert schedulers)`.
2. `agent/extensions/pasto-legal-tools.js` — remove the
   `// ── Alert Schedulers (benchmark — mocked) ──` and
   `// ── List / delete schedulers (benchmark — mocked) ──` blocks.
3. `agent/tools/benchmark.py` — remove the alert classes (`BiomassAlert`,
   `RainAlert`, `VigorAlert`, `StockingRateAlert`), `list_schedulers`,
   `delete_scheduler`, `MOCKED_SCHEDULERS`, the operator helpers, and
   their entries in `ACTIONS`.

**Forage / paddock / herd tools (`pasture`, `paddock`, `herd`) — 8 tools:**
1. `agent/registry.py` — remove the 8 entries in `TOOLS` under the
   `# ═══ Forage budget`, `# ═══ Paddock management`, and
   `# ═══ Vaccination calendar` sections, and the 8 entries in
   `ACTION_MAP` under `# benchmark (mocked forage budget / paddock /
   vaccination)`.
2. `agent/extensions/pasto-legal-tools.js` — remove the
   `// ── Forage budget, paddock & herd tools (benchmark — mocked) ──`
   block (8 `pi.registerTool` calls).
3. `agent/tools/benchmark.py` — remove the entire `# ── Paddock & herd
   tools (benchmark — mocked) ──` section (the `_mock_pasture_stats_dict`,
   `_mock_topographic_stats_dict`, `_PASTURE_STATS_TEMPLATE`,
   `_find_paddock` helpers and all 8 functions) and their entries in
   `ACTIONS` under `# pasture-benchmark / paddock-benchmark / herd-benchmark`.

If all benchmark categories are removed, the entire `benchmark.py` file
can be deleted along with all its `ACTION_MAP` entries.

No production code (`property.py`, `gee.py`, `feedback.py`, `tts.py`,
`onboarding.py`, `version.py`) is touched by any deletion.