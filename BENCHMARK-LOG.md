# Pasto Legal — Benchmark Implementation Log

Companion to **`BENCHMARK.md`** (the manual — architecture, methodology,
patterns). This file records **what has been implemented so far**, the
per-tool implementation decisions, where the code lives, and how to tear
it all down when benchmarking is finished. Update this file every time a
new scale point or mocked-tool batch lands.

The canonical methodology, hypotheses, metrics, test corpus shape, and
pattern-level decisions live in `BENCHMARK.md` and are not duplicated
here.

---

## 1. Status

| Scale | Total tools | Added vs. baseline | Step | Status |
|-------|-------------|--------------------|------|--------|
| 1     | ~20         | 0                  | Baseline (`refac/pi-sdk-develop`) | ✅ Done (production) |
| 2     | ~28         | +8 alert           | Alert schedulers (biomass/rain/vigor/stocking-rate confirm pairs) | ✅ Done |
| 3     | ~41         | +9 weather         | Weather mocks (read-only) | ✅ Done |
| 4     | ~49         | +8 pasture/paddock/herd | Forage budget, paddock CRUD + stats + rotation, vaccination calendar | ✅ Done |
| 5     | ~60         | +~11               | Future filler batches | ⏳ Pending |
| 6     | ~120        | +~60               | Future filler batches | ⏳ Pending |

**Current registry size:** ~49 tools (production + mocked benchmark tools).
**Test corpus:** not yet materialized — the prompt *shape* is defined in
`BENCHMARK.md` §5; the actual corpus will be added alongside the Step 5
filler batches.

---

## 2. Implemented tools by category

All tools below are **mocked** (canned JSON returns, no backend/DB/WhatsApp)
unless noted otherwise. They follow the mocked-tool contract in
`BENCHMARK.md` §3 (registered in JS, indexed in `TOOLS`, mapped in
`ACTION_MAP`, implemented in `benchmark.py`, session state in Valkey).

### `alert` — 10 tools, two-step confirm flow (Step 2)
- `request_biomass_alert` (+ `skill`), `confirm_biomass_alert`
- `request_rain_alert` (+ `skill`), `confirm_rain_alert`
- `request_vigor_alert` (+ `skill`), `confirm_vigor_alert`
- `request_stocking_rate_alert` (+ `skill`), `confirm_stocking_rate_alert`
- `list_schedulers` (skill-less)
- `delete_scheduler` (skill-less)

### `weather` — 9 tools, read-only, skill-less (Step 3)
- `get_rain_forecast_15_days`
- `get_rain_forecast_months`
- `get_rain_history`
- `get_weather_today`
- `get_temperature_forecast_15_days`
- `get_drought_index`
- `get_evapotranspiration`
- `get_soil_moisture`
- `get_climate_summary`

### `pasture` — 1 tool (Step 4)
- `get_forage_budget` (+ `skill`)

### `paddock` — 6 tools (Step 4)
- `auto_generate_paddocks` (+ `skill`)
- `set_paddock_label` (skill-less)
- `delete_paddock` (skill-less)
- `get_paddock_pasture_stats` (skill-less)
- `get_paddock_topographic_stats` (skill-less)
- `get_rotation_schedule` (+ `skill`)

### `herd` — 1 tool (Step 4)
- `get_vaccination_calendar` (+ `skill`)

### Production tools (not benchmark) — for reference
`property` (register/remove/rename), `analysis` (pasture/topographic stats,
image generation, UA calculator), `utility` (`generate_speech`,
`consult_update_notes`), `onboarding` (`accept_terms_and_conditions`),
`feedback` (`request_feedback`, `save_feedback`).

---

## 3. Implementation-specific decisions

These are the *per-tool / per-batch* decisions made while implementing the
mocked tools. The general/pattern decisions (per-type confirm pairs,
session-state pending pattern, mocked returns, `registry.py` updates,
alerts not in `ALWAYS_AVAILABLE`, `category` grouping, all operators
available, default operator conventions, "no per-tool docs in the manual")
live in `BENCHMARK.md` §7 and are not repeated here.

### Weather (Step 3)
- **Skill-less read-only mocks.** Unlike the alert tools (which carry
  `skill` blocks for the two-step confirm flow), the 9 weather tools have
  no skill — they are pure data-retrieval mocks. This intentionally tests
  whether the LLM calls them correctly based only on the `description`
  field, without step-by-step skill guidance. It also keeps prompt
  injection lean (no extra skill text) and makes the disambiguation task
  harder (the LLM must choose between similarly-named tools from
  description alone).
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
  This makes benchmark results reproducible while still appearing realistic
  (Cerrado wet season Oct–Mar, dry season May–Sep).
- **`category: "weather"`** for all 9 tools — descriptive only (RAG uses
  the `name: description` embedding), and serves as the deletion key (§5).

### Pasture / paddock / herd (Step 4)
- **Three new categories: `pasture`, `paddock`, `herd`.** Each is
  semantically distinct from production categories and from each other,
  aiding RAG disambiguation. `pasture` (forage budget) bridges analysis +
  herd; `paddock` groups CRUD + per-paddock stats + rotation; `herd`
  groups vaccination and future herd-health tools.
- **Paddock state mirrors property state.** Paddocks are stored in Valkey
  under `session:{user_id}` → `all_paddocks` (list of dicts with `id`,
  `label`, `area_ha`, `car_code`), mirroring the property `all_properties`
  pattern. CRUD tools (`auto_generate_paddocks`, `set_paddock_label`,
  `delete_paddock`) read/write this key and return `session_state` so the
  JS extension's `makeResult` plumbing works unchanged.
- **Per-paddock stats match real schema shapes.** `get_paddock_pasture_stats`
  returns a `PastureStats.model_dump()`-shaped dict (4 optional nested
  `*_stats` sections with `observation_year`, `amount: {value, unity}`, or
  `data: [{..., amount}]`); `get_paddock_topographic_stats` returns
  `{elevation: {value, unity}, slope: {value, unity}}`. Both also return
  `stats_text` (formatted Portuguese string) — the only field the LLM
  currently sees via `makeResult({message: result.stats_text})`.
- **No per-paddock image tools.** Per the decision to skip mocked image
  generation for paddocks, only the two stats tools were implemented (no
  `get_paddock_biomass_image`, etc.). This keeps the paddock tool count
  lean and avoids the complexity of generating mock base64 PNGs.
- **`set_paddock_label` merges set + update.** Instead of separate
  `set_paddock_label` and `update_paddock_label` tools (which would be
  semantically identical), a single tool handles both creating and renaming
  labels — identified by `paddock_id` only.
- **`get_forage_budget` requires `herd_size_ua`.** The tool returns an
  error if herd size is not provided. The skill instructs the LLM to ask
  the user for herd size before calling the tool — a parameter-gathering
  step that the alert tools do not exercise.
- **`get_rotation_schedule` auto-falls-back.** If no paddocks exist in
  session state, the tool mocks 4 default paddocks instead of erroring.
  This lets the benchmark test the tool in isolation (without a prior
  `auto_generate_paddocks` call), but the skill still recommends
  generating paddocks first for a realistic flow.
- **`get_vaccination_calendar` is Cerrado/Centro-Oeste focused.** The
  mocked calendar reflects LAPIG/UFG's regional focus (Goiás): Aftosa in
  May + November, Brucelose for females 3–8 months, annual
  Raiva/Carbúnculo/Clostridioses/Botulismo. The skill instructs the LLM to
  always caveat that it's a reference calendar and to consult a vet.

---

## 4. Where the code lives

| Layer | File | What's there |
|-------|------|--------------|
| Tool implementations | `agent/tools/benchmark.py` | All mocked tool classes/functions + `ACTIONS` dict + `__main__` CLI entry. Sectioned by `# ── ... (benchmark — mocked) ──` comment markers. |
| Registry / RAG index | `agent/registry.py` | `TOOLS` entries (name, description, category, optional `skill`) + `ACTION_MAP` entries for `/tool` dispatch. Sectioned by `# ═══ ... (benchmark — mocked) ═══` markers. |
| JS extension | `agent/extensions/pasto-legal-tools.js` | `pi.registerTool` calls for every mocked tool. Sectioned by `// ── ... (benchmark — mocked) ──` markers. |
| `/tool` dispatcher | `agent/tools/benchmark.py` (`ACTIONS`) | Each `action` maps to a class method or function; invoked by `api/main.py` `/tool` endpoint via base64-json args. |
| Session state | Valkey `session:{user_id}` | `pending_alert` (alerts), `all_paddocks` (paddock CRUD). Mirrors `property.py`'s `pending_*` / `all_properties` patterns. |

Per-tool semantics (parameters, return shapes, operator lists) live in the
docstrings of `agent/tools/benchmark.py` and the `skill` blocks in
`agent/registry.py` — not in `BENCHMARK.md` (per the "no per-tool docs in
the manual" decision).

---

## 5. Deletion guide — removing all benchmark mocked tools

All benchmark mocked tools are organized so they can be deleted in one
sweep per category when testing is finished. Each category is tagged with
a comment marker in the source files (see §4 for the marker strings).

### Weather tools (`category: "weather"`) — 9 tools, read-only
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

### Alert tools (`category: "alert"`) — 10 tools, two-step confirm flow
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

### Forage / paddock / herd tools (`pasture`, `paddock`, `herd`) — 8 tools
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

---

## 6. Pending work

- **Step 5 (~60 tools):** +~11 filler tools across varied categories to
  stress Tool-RAG disambiguation. Introduce new mocked categories to keep
  descriptions diverse.
- **Step 6 (~120 tools):** +~60 filler tools. The benchmark harness is
  designed so filler batches slot in without changing the test corpus or
  metric collection.
- **Test corpus:** materialize the prompt set defined in `BENCHMARK.md` §5
  into runnable fixtures, with fresh-session and continuation variants and
  the separate-turn "sim" confirmation.
- **Aggregation:** a script to collect `run_metrics` log lines across
  scale points and produce the comparison tables for H1/H2/H3.