"""
CLI wrapper for benchmark alert-scheduler tools (mocked).

All tools in this module are *mocked* — they return canned JSON without
hitting any real backend, database, or WhatsApp scheduler. They exist to
grow the agent's tool registry so we can benchmark single-agent quality
and cost as the number of tools increases. See BENCHMARK.md.

Architecture mirrors agent/tools/feedback.py and agent/tools/property.py:
  - Each alert type is a class with `request` and `confirm` methods.
  - `request_*` stashes a pending scheduler in session_state (Valkey) and
    returns a human-readable plan asking for confirmation.
  - `confirm_*` resolves the pending scheduler, returns a confirmation
    echoing the condition set, and clears the pending state.
  - The ACTIONS dict maps action_name -> bound method, dispatched from
    the __main__ CLI entry (base64-json args, identical to other tools).

Usage:
  python agent/tools/benchmark.py '<base64-json-args>'

Session-state keys (mirrors property.py's pending-registration pattern):
  - pending_alert : dict | None
      {"type": "biomass"|"rain"|"vigor"|"stocking_rate",
       "condition": str, "operator": str, "threshold": float,
       "car_codes": list[str], "channel": "whatsapp"}
"""
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))

valkey = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, db=VALKEY_DB, decode_responses=True)


# ── Session state helpers (mirror property.py) ────────────────────────────

def _get_state(user_id: str) -> dict:
    raw = valkey.get(f"session:{user_id}")
    return json.loads(raw) if raw else {}


def _set_state(user_id: str, state: dict) -> None:
    valkey.set(f"session:{user_id}", json.dumps(state, default=str))


# ── Operator vocabulary ────────────────────────────────────────────────────
# Shared by biomass (and reusable by any threshold-based alert). All common
# logic operators available so the LLM must map natural-language phrasing
# ("maior que", "no mínimo", "igual a") to the right operator — a non-trivial
# retrieval/selection task that exercises the benchmark.
OPERATORS = ("gt", "lt", "le", "ge", "eq", "neq")

_OPERATOR_LABELS = {
    "gt": "maior que",
    "lt": "menor que",
    "le": "menor ou igual a",
    "ge": "maior ou igual a",
    "eq": "igual a",
    "neq": "diferente de",
}


def _operator_label(op: str) -> str:
    return _OPERATOR_LABELS.get(op, op)


def _describe_pending(pending: dict) -> str:
    """Human-readable description of a pending alert (used by request_*)."""
    t = pending.get("type", "?")
    op = _operator_label(pending.get("operator", ""))
    thr = pending.get("threshold", "?")
    unit = pending.get("unit", "")
    car = ", ".join(pending.get("car_codes", []) or ["(propriedade atual)"])
    return (
        f"Vou criar um alerta via WhatsApp para a propriedade {car} que dispara "
        f"quando {t} for *{op}* {thr}{unit}. Confirma? Responda SIM."
    )


def _confirm_message(pending: dict) -> str:
    """Confirmation message echoing the registered condition (confirm_*)."""
    t = pending.get("type", "?")
    op = _operator_label(pending.get("operator", ""))
    thr = pending.get("threshold", "?")
    unit = pending.get("unit", "")
    car = ", ".join(pending.get("car_codes", []) or ["(propriedade atual)"])
    return (
        f"Alerta cadastrado! Você receberá um aviso no WhatsApp quando {t} "
        f"for *{op}* {thr}{unit} para a propriedade {car}."
    )


# ── Mocked scheduler list (benchmark — fixed canned list) ───────────────
# A fixed in-memory list of already-registered schedulers, used by
# `list_schedulers` and `delete_scheduler`. The list is module-level (shared
# across calls within a single API process) and intentionally NOT persisted
# to Valkey — it is a mocked fixture, not real state. Every user/property
# sees the same list, which is fine for the benchmark's growth-axis test
# (we only care that Tool-RAG surfaces these tools and the LLM calls them
# correctly).
MOCKED_SCHEDULERS = [
    {
        "name": "Alerta de Biomassa - Fazenda Primavera",
        "condition": "biomassa maior que 2500 kg/ha",
    },
    {
        "name": "Alerta de Chuva - Fazenda Primavera",
        "condition": "chuva acumulada maior que 80 mm em 7 dias",
    },
    {
        "name": "Alerta de Vigor - Pasto Norte",
        "condition": "vigor (NDVI) menor que 0.4",
    },
    {
        "name": "Alerta de Lotação - Pasto Norte",
        "condition": "lotação (UA/ha) maior que 2.5 UA/ha",
    },
]


def list_schedulers(args: dict) -> dict:
    """Return the mocked list of registered schedulers (name + condition).

    Mocked — returns a fixed canned list (MOCKED_SCHEDULERS). Used by the
    benchmark to exercise Tool-RAG retrieval and the LLM's list/update flow.
    See BENCHMARK.md.
    """
    schedulers = MOCKED_SCHEDULERS
    if not schedulers:
        return {"message": "Nenhum agendamento de alerta cadastrado."}
    lines = ["*Agendamentos de alerta ativos:*"]
    for i, s in enumerate(schedulers, start=1):
        lines.append(f"{i}. *{s['name']}* — {s['condition']}")
    return {"message": "\n".join(lines), "schedulers": schedulers}


def delete_scheduler(args: dict) -> dict:
    """Delete a mocked scheduler by name or by its 1-indexed position.

    Parameters:
      - user_id : str (required, from session context)
      - name    : str  (optional) — scheduler name (exact match)
      - number  : int  (optional) — 1-indexed position in list_schedulers output

    Exactly one of `name` or `number` must be provided. Mocked — mutates
    the in-memory MOCKED_SCHEDULERS list; the change is NOT persisted to
    Valkey and resets when the API process restarts. See BENCHMARK.md.
    """
    name = args.get("name")
    number = args.get("number")
    if name is None and number is None:
        return {"error": "Forneça 'name' ou 'number' para identificar o agendamento."}
    if name is not None and number is not None:
        return {"error": "Forneça apenas 'name' ou apenas 'number', não ambos."}

    target_idx = None
    if name is not None:
        for i, s in enumerate(MOCKED_SCHEDULERS):
            if s["name"] == name:
                target_idx = i
                break
        if target_idx is None:
            return {"error": f"Nenhum agendamento encontrado com o nome '{name}'."}
    else:
        try:
            n = int(number)
        except (TypeError, ValueError):
            return {"error": f"'number' deve ser um inteiro (recebido: {number!r})."}
        if n < 1 or n > len(MOCKED_SCHEDULERS):
            return {
                "error": (
                    f"Número {n} fora do intervalo. "
                    f"Use 1 a {len(MOCKED_SCHEDULERS)}."
                )
            }
        target_idx = n - 1

    removed = MOCKED_SCHEDULERS.pop(target_idx)
    return {
        "message": (
            f"Agendamento *{removed['name']}* "
            f"({removed['condition']}) removido."
        ),
        "removed": removed,
    }


# ── Weather tools (benchmark — mocked) ────────────────────────────────────
# weather-benchmark: read-only mocked weather/rain data tools. All return
# canned JSON tables (max 5 attributes per row) without hitting any backend.
# Grouped under category "weather" in registry.py so they can be removed in
# one sweep (see BENCHMARK.md §8). No session_state, no confirm flow — these
# are pure data-retrieval mocks that stress Tool-RAG disambiguation between
# similarly-named weather concepts (rain forecast vs history vs today,
# rain vs temperature vs evapotranspiration vs soil moisture, etc.).

import calendar
import datetime as _dt

# Shared 5-attribute rain-row shape used by forecast/history/today:
#   date, precipitation_mm, precipitation_max_mm, precipitation_min_mm,
#   probability_pct
# Deterministic pseudo-data keyed off the date string so repeated calls are
# stable within a process. Values are illustrative for the Cerrado/goiano
# pasture region (wet season Oct–Mar, dry season May–Sep).

_WET_MONTHS = {10, 11, 12, 1, 2, 3}


def _rain_for_day(date_str: str, month: int) -> dict:
    """Deterministic mocked rain row for a single day."""
    seed = sum(ord(c) for c in date_str)
    base = 18.0 if month in _WET_MONTHS else 2.0
    precip = round(base + (seed % 30) * 0.7, 1)
    pmax = round(precip + 5 + (seed % 12), 1)
    pmin = round(max(0.0, precip - 4 - (seed % 8)), 1)
    prob = min(95, 40 + (seed % 50)) if month in _WET_MONTHS else min(30, seed % 25)
    return {
        "date": date_str,
        "precipitation_mm": precip,
        "precipitation_max_mm": pmax,
        "precipitation_min_mm": pmin,
        "probability_pct": prob,
    }


def _rain_table_message(rows: list, title: str) -> dict:
    """Format a list of rain rows into a WhatsApp-style message + table."""
    lines = [f"*{title}*", ""]
    lines.append("Data | Chuva (mm) | Máx | Mín | Prob (%)")
    lines.append("-----|-------------|-----|-----|---------")
    for r in rows:
        lines.append(
            f"{r['date']} | {r['precipitation_mm']} | "
            f"{r['precipitation_max_mm']} | {r['precipitation_min_mm']} | "
            f"{r['probability_pct']}"
        )
    return {"message": "\n".join(lines), "table": rows}


def get_rain_forecast_15_days(args: dict) -> dict:
    """Mocked 15-day rain forecast (daily precipitation table).

    Returns 15 rows, one per day starting today, with precipitation_mm,
    precipitation_max_mm, precipitation_min_mm, probability_pct. Mocked —
    no real weather API. See BENCHMARK.md.
    """
    today = _dt.date.today()  # noqa: DTZ011  # noqa: DTZ011
    rows = []
    for i in range(15):
        d = today + _dt.timedelta(days=i)
        rows.append(_rain_for_day(d.isoformat(), d.month))
    return _rain_table_message(rows, "Previsão de chuva — 15 dias")


def get_rain_forecast_months(args: dict) -> dict:
    """Mocked monthly rain forecast (1 to 3 months ahead).

    Parameters:
      - months : int (1–3, required) — how many months ahead to forecast
      - car_codes : list[str] (optional)

    Returns one row per month with aggregated precipitation (max/min/prob).
    Mocked — no real weather API. See BENCHMARK.md.
    """
    months = args.get("months", 1)
    try:
        months = int(months)
    except (TypeError, ValueError):
        return {"error": f"'months' deve ser um inteiro (recebido: {months!r})."}
    if months < 1 or months > 3:
        return {"error": f"'months' deve estar entre 1 e 3 (recebido: {months})."}

    today = _dt.date.today()  # noqa: DTZ011
    rows = []
    for i in range(months):
        ym = (today.year, today.month + i)
        while ym[1] > 12:
            ym = (ym[0] + 1, ym[1] - 12)
        y, m = ym
        label = f"{y}-{m:02d}"
        wet = m in _WET_MONTHS
        seed = (y * 12 + m) % 97
        total = round((180 if wet else 25) + (seed % 80), 1)
        rows.append({
            "month": label,
            "precipitation_mm": total,
            "precipitation_max_mm": round(total + 40 + (seed % 30), 1),
            "precipitation_min_mm": round(max(0.0, total - 50 - (seed % 20)), 1),
            "probability_pct": (75 + (seed % 20)) if wet else (15 + (seed % 20)),
        })
    lines = [f"*Previsão de chuva — {months} mês(es)*", ""]
    lines.append("Mês | Chuva (mm) | Máx | Mín | Prob (%)")
    lines.append("----|------------|-----|-----|---------")
    for r in rows:
        lines.append(
            f"{r['month']} | {r['precipitation_mm']} | "
            f"{r['precipitation_max_mm']} | {r['precipitation_min_mm']} | "
            f"{r['probability_pct']}"
        )
    return {"message": "\n".join(lines), "table": rows}


def get_rain_history(args: dict) -> dict:
    """Mocked rain history for a specific past month (daily rows).

    Parameters:
      - month : int (1–12, required)
      - year  : int (required, must be in the past)
      - car_codes : list[str] (optional)

    Returns one row per day of that month with the same 5-attribute rain
    shape. Mocked — no real weather API. See BENCHMARK.md.
    """
    month = args.get("month")
    year = args.get("year")
    try:
        month = int(month); year = int(year)
    except (TypeError, ValueError):
        return {"error": "'month' e 'year' são obrigatórios e devem ser inteiros."}
    if month < 1 or month > 12:
        return {"error": f"'month' deve estar entre 1 e 12 (recebido: {month})."}
    today = _dt.date.today()  # noqa: DTZ011
    if (year, month) > (today.year, today.month):
        return {"error": f"'year'/'month' deve ser no passado (recebido: {year}-{month:02d})."}

    ndays = calendar.monthrange(year, month)[1]
    rows = []
    for day in range(1, ndays + 1):
        d = _dt.date(year, month, day)
        rows.append(_rain_for_day(d.isoformat(), month))
    return _rain_table_message(rows, f"Histórico de chuva — {year}-{month:02d}")


def get_weather_today(args: dict) -> dict:
    """Mocked current weather conditions for today.

    Returns a single row with date, precipitation_mm, temp_c, humidity_pct,
    condition (e.g. "chuva leve", "ensolarado"). Mocked — no real weather
    API. See BENCHMARK.md.
    """
    today = _dt.date.today()  # noqa: DTZ011
    m = today.month
    seed = sum(ord(c) for c in today.isoformat())
    wet = m in _WET_MONTHS
    precip = round((12 + (seed % 20)) if wet else (0 + (seed % 4)), 1)
    temp = round((24 + (seed % 8)) if wet else (28 + (seed % 6)), 1)
    humidity = (70 + (seed % 25)) if wet else (35 + (seed % 20))
    condition = (
        "chuva forte" if precip > 20 else
        "chuva leve" if precip > 5 else
        "nublado" if humidity > 60 else
        "ensolarado"
    )
    row = {
        "date": today.isoformat(),
        "precipitation_mm": precip,
        "temp_c": temp,
        "humidity_pct": humidity,
        "condition": condition,
    }
    msg = (
        f"*Tempo agora ({row['date']})*\n"
        f"Chuva: {row['precipitation_mm']} mm\n"
        f"Temp: {row['temp_c']} °C\n"
        f"Umidade: {row['humidity_pct']}%\n"
        f"Condição: {row['condition']}"
    )
    return {"message": msg, "table": [row]}


def get_temperature_forecast_15_days(args: dict) -> dict:
    """Mocked 15-day temperature forecast (daily max/min/avg °C).

    Returns 15 rows: date, temp_max_c, temp_min_c, temp_avg_c, condition.
    Mocked — no real weather API. See BENCHMARK.md.
    """
    today = _dt.date.today()  # noqa: DTZ011
    rows = []
    for i in range(15):
        d = today + _dt.timedelta(days=i)
        seed = sum(ord(c) for c in d.isoformat())
        wet = d.month in _WET_MONTHS
        tmax = round((28 + (seed % 8)) if wet else (32 + (seed % 6)), 1)
        tmin = round((16 + (seed % 6)) if wet else (14 + (seed % 5)), 1)
        tavg = round((tmax + tmin) / 2, 1)
        cond = "chuva" if wet and seed % 3 == 0 else ("nublado" if seed % 4 == 0 else "sol")
        rows.append({
            "date": d.isoformat(),
            "temp_max_c": tmax,
            "temp_min_c": tmin,
            "temp_avg_c": tavg,
            "condition": cond,
        })
    lines = ["*Previsão de temperatura — 15 dias*", ""]
    lines.append("Data | Máx (°C) | Mín (°C) | Méd (°C) | Condição")
    lines.append("-----|-----------|-----------|-----------|---------")
    for r in rows:
        lines.append(f"{r['date']} | {r['temp_max_c']} | {r['temp_min_c']} | {r['temp_avg_c']} | {r['condition']}")
    return {"message": "\n".join(lines), "table": rows}


def get_drought_index(args: dict) -> dict:
    """Mocked drought index (SPEI-like) for a month/region.

    Parameters:
      - month : int (1–12, required)
      - year  : int (required)

    Returns month, index (-3..+3), category, trend, region. Negative index
    = drought. Mocked — no real climate model. See BENCHMARK.md.
    """
    month = args.get("month"); year = args.get("year")
    try:
        month = int(month); year = int(year)
    except (TypeError, ValueError):
        return {"error": "'month' e 'year' são obrigatórios e devem ser inteiros."}
    if month < 1 or month > 12:
        return {"error": f"'month' deve estar entre 1 e 12 (recebido: {month})."}
    seed = (year * 12 + month) % 37
    wet = month in _WET_MONTHS
    index = round(((seed % 30) / 10.0 - 1.5) if not wet else ((seed % 20) / 10.0 - 0.5), 2)
    if index <= -2.0:
        category = "severo"
    elif index <= -1.0:
        category = "seco"
    elif index < 1.0:
        category = "normal"
    else:
        category = "úmido"
    trend = ["estável", "piorando", "melhorando"][seed % 3]
    row = {
        "month": f"{year}-{month:02d}",
        "index": index,
        "category": category,
        "trend": trend,
        "region": "Cerrado",
    }
    msg = (
        f"*Índice de seca — {row['month']}*\n"
        f"Índice: {row['index']}\n"
        f"Categoria: {row['category']}\n"
        f"Tendência: {row['trend']}\n"
        f"Região: {row['region']}"
    )
    return {"message": msg, "table": [row]}


def get_evapotranspiration(args: dict) -> dict:
    """Mocked reference evapotranspiration (ET₀, mm/day) for a month.

    Parameters:
      - month : int (1–12, required)
      - year  : int (required)

    Returns month, et0_mm_day, et0_total_mm, temp_avg_c, humidity_pct.
    Mocked — no real climate model. See BENCHMARK.md.
    """
    month = args.get("month"); year = args.get("year")
    try:
        month = int(month); year = int(year)
    except (TypeError, ValueError):
        return {"error": "'month' e 'year' são obrigatórios e devem ser inteiros."}
    if month < 1 or month > 12:
        return {"error": f"'month' deve estar entre 1 e 12 (recebido: {month})."}
    seed = (year * 12 + month) % 41
    wet = month in _WET_MONTHS
    et0 = round((3.2 + (seed % 15) / 10.0) if not wet else (4.5 + (seed % 10) / 10.0), 2)
    ndays = calendar.monthrange(year, month)[1]
    total = round(et0 * ndays, 1)
    tavg = round((22 + (seed % 8)) if wet else (26 + (seed % 6)), 1)
    humidity = (70 + (seed % 20)) if wet else (40 + (seed % 25))
    row = {
        "month": f"{year}-{month:02d}",
        "et0_mm_day": et0,
        "et0_total_mm": total,
        "temp_avg_c": tavg,
        "humidity_pct": humidity,
    }
    msg = (
        f"*Evapotranspiração (ET₀) — {row['month']}*\n"
        f"ET₀ diária: {row['et0_mm_day']} mm/dia\n"
        f"ET₀ total: {row['et0_total_mm']} mm\n"
        f"Temp média: {row['temp_avg_c']} °C\n"
        f"Umidade: {row['humidity_pct']}%"
    )
    return {"message": msg, "table": [row]}


def get_soil_moisture(args: dict) -> dict:
    """Mocked soil moisture (%) for a property today.

    Returns date, moisture_pct, moisture_max_pct, moisture_min_pct, depth_cm.
    Mocked — no real sensor data. See BENCHMARK.md.
    """
    today = _dt.date.today()  # noqa: DTZ011
    m = today.month
    seed = sum(ord(c) for c in today.isoformat())
    wet = m in _WET_MONTHS
    base = (55 + (seed % 20)) if wet else (20 + (seed % 15))
    row = {
        "date": today.isoformat(),
        "moisture_pct": base,
        "moisture_max_pct": min(100, base + 8 + (seed % 6)),
        "moisture_min_pct": max(0, base - 10 - (seed % 5)),
        "depth_cm": 30,
    }
    msg = (
        f"*Umidade do solo — {row['date']}*\n"
        f"Umidade: {row['moisture_pct']}%\n"
        f"Máx: {row['moisture_max_pct']}% | Mín: {row['moisture_min_pct']}%\n"
        f"Profundidade: {row['depth_cm']} cm"
    )
    return {"message": msg, "table": [row]}


def get_climate_summary(args: dict) -> dict:
    """Mocked yearly climate summary for a region.

    Parameters:
      - year : int (required)

    Returns year, total_rain_mm, avg_temp_c, dry_months, wet_months.
    Mocked — no real climate model. See BENCHMARK.md.
    """
    year = args.get("year")
    try:
        year = int(year)
    except (TypeError, ValueError):
        return {"error": "'year' é obrigatório e deve ser inteiro."}
    seed = year % 53
    total = round(1400 + (seed % 400), 1)
    avg_temp = round(24 + (seed % 4), 1)
    row = {
        "year": year,
        "total_rain_mm": total,
        "avg_temp_c": avg_temp,
        "dry_months": 5,
        "wet_months": 7,
    }
    msg = (
        f"*Resumo climático — {row['year']}*\n"
        f"Chuva total: {row['total_rain_mm']} mm\n"
        f"Temp média: {row['avg_temp_c']} °C\n"
        f"Meses secos: {row['dry_months']}\n"
        f"Meses chuvosos: {row['wet_months']}"
    )
    return {"message": msg, "table": [row]}


# ── Alert tool classes ─────────────────────────────────────────────────────
# Each class owns a domain-specific alert. `request` plans the scheduler and
# stashes it in session_state; `confirm` registers (mocked) and clears it.
# All returns follow the same shape as feedback.py / property.py so the JS
# extension's makeResult() works unchanged.

class BiomassAlert:
    """Biomass (dry-matter, kg/ha) threshold alert — all logic operators."""

    TYPE = "biomassa"
    UNIT = " kg/ha"

    @staticmethod
    def request(args: dict) -> dict:
        user_id = args["user_id"]
        operator = args.get("operator", "gt")
        if operator not in OPERATORS:
            return {"error": f"Operador inválido: {operator}. Use um de {OPERATORS}."}
        threshold = args["threshold"]
        car_codes = args.get("car_codes", [])

        state = _get_state(user_id)
        pending = {
            "type": BiomassAlert.TYPE,
            "operator": operator,
            "threshold": threshold,
            "unit": BiomassAlert.UNIT,
            "car_codes": car_codes,
            "channel": "whatsapp",
        }
        state["pending_alert"] = pending
        _set_state(user_id, state)

        return {
            "message": _describe_pending(pending),
            "session_state": state,
        }

    @staticmethod
    def confirm(args: dict) -> dict:
        user_id = args["user_id"]
        state = _get_state(user_id)
        pending = state.get("pending_alert")
        if not pending or pending.get("type") != BiomassAlert.TYPE:
            return {
                "message": "Nenhum alerta de biomassa pendente de confirmação.",
                "session_state": state,
            }
        state["pending_alert"] = None
        _set_state(user_id, state)
        return {
            "message": _confirm_message(pending),
            "session_state": state,
        }


class RainAlert:
    """Accumulated rainfall (mm) threshold alert."""

    TYPE = "chuva acumulada"
    UNIT = " mm"

    @staticmethod
    def request(args: dict) -> dict:
        user_id = args["user_id"]
        operator = args.get("operator", "gt")
        if operator not in OPERATORS:
            return {"error": f"Operador inválido: {operator}. Use um de {OPERATORS}."}
        threshold = args["threshold"]
        window_days = args.get("window_days", 7)
        car_codes = args.get("car_codes", [])

        state = _get_state(user_id)
        pending = {
            "type": RainAlert.TYPE,
            "operator": operator,
            "threshold": threshold,
            "unit": RainAlert.UNIT,
            "window_days": window_days,
            "car_codes": car_codes,
            "channel": "whatsapp",
        }
        state["pending_alert"] = pending
        _set_state(user_id, state)

        return {
            "message": _describe_pending(pending),
            "session_state": state,
        }

    @staticmethod
    def confirm(args: dict) -> dict:
        user_id = args["user_id"]
        state = _get_state(user_id)
        pending = state.get("pending_alert")
        if not pending or pending.get("type") != RainAlert.TYPE:
            return {
                "message": "Nenhum alerta de chuva pendente de confirmação.",
                "session_state": state,
            }
        state["pending_alert"] = None
        _set_state(user_id, state)
        return {
            "message": _confirm_message(pending),
            "session_state": state,
        }


class VigorAlert:
    """Vegetative vigor (NDVI) drop-below-threshold alert.

    NDVI degrades when pasture is overgrazed or drying out — the operator
    is fixed to `lt` (drop below) by domain convention, but kept as an
    explicit parameter so the LLM must still choose it.
    """

    TYPE = "vigor (NDVI)"
    UNIT = ""

    @staticmethod
    def request(args: dict) -> dict:
        user_id = args["user_id"]
        operator = args.get("operator", "lt")
        if operator not in OPERATORS:
            return {"error": f"Operador inválido: {operator}. Use um de {OPERATORS}."}
        threshold = args["threshold"]
        car_codes = args.get("car_codes", [])

        state = _get_state(user_id)
        pending = {
            "type": VigorAlert.TYPE,
            "operator": operator,
            "threshold": threshold,
            "unit": VigorAlert.UNIT,
            "car_codes": car_codes,
            "channel": "whatsapp",
        }
        state["pending_alert"] = pending
        _set_state(user_id, state)

        return {
            "message": _describe_pending(pending),
            "session_state": state,
        }

    @staticmethod
    def confirm(args: dict) -> dict:
        user_id = args["user_id"]
        state = _get_state(user_id)
        pending = state.get("pending_alert")
        if not pending or pending.get("type") != VigorAlert.TYPE:
            return {
                "message": "Nenhum alerta de vigor pendente de confirmação.",
                "session_state": state,
            }
        state["pending_alert"] = None
        _set_state(user_id, state)
        return {
            "message": _confirm_message(pending),
            "session_state": state,
        }


class StockingRateAlert:
    """Stocking rate (UA/ha) exceeds support-capacity alert.

    UA = Unidade Animal (1 UA = 450 kg). Triggered when lotação real
    exceeds the ideal support capacity computed by the LAPIG methodology.
    """

    TYPE = "lotação (UA/ha)"
    UNIT = " UA/ha"

    @staticmethod
    def request(args: dict) -> dict:
        user_id = args["user_id"]
        operator = args.get("operator", "gt")
        if operator not in OPERATORS:
            return {"error": f"Operador inválido: {operator}. Use um de {OPERATORS}."}
        threshold = args["threshold"]
        car_codes = args.get("car_codes", [])

        state = _get_state(user_id)
        pending = {
            "type": StockingRateAlert.TYPE,
            "operator": operator,
            "threshold": threshold,
            "unit": StockingRateAlert.UNIT,
            "car_codes": car_codes,
            "channel": "whatsapp",
        }
        state["pending_alert"] = pending
        _set_state(user_id, state)

        return {
            "message": _describe_pending(pending),
            "session_state": state,
        }

    @staticmethod
    def confirm(args: dict) -> dict:
        user_id = args["user_id"]
        state = _get_state(user_id)
        pending = state.get("pending_alert")
        if not pending or pending.get("type") != StockingRateAlert.TYPE:
            return {
                "message": "Nenhum alerta de lotação pendente de confirmação.",
                "session_state": state,
            }
        state["pending_alert"] = None
        _set_state(user_id, state)
        return {
            "message": _confirm_message(pending),
            "session_state": state,
        }


# ── Paddock & herd tools (benchmark — mocked) ─────────────────────────────
# pasture-benchmark / paddock-benchmark / herd-benchmark: mocked tools for
# forage budget, paddock management, per-paddock pasture stats, rotation
# scheduling, and vaccination calendar. All return canned JSON without
# hitting any backend. Grouped under categories "pasture", "paddock", and
# "herd" in registry.py so they can be removed in one sweep per category
# (see BENCHMARK.md §8). Paddock state is persisted in Valkey under
# session:{user_id} mirroring the property registration pattern.


def _mock_pasture_stats_dict(paddock_label: str = "Pasto") -> dict:
    """Return a mocked PastureStats.model_dump()-shaped dict."""
    return {
        "biomass_stats": {
            "observation_year": 2026,
            "amount": {"value": 2340.5, "unity": "tonelada(s) de matéria seca acumulada no mês"},
        },
        "age_stats": {
            "observation_year": 2024,
            "data": [
                {"age": "1-10", "amount": {"value": 12.5, "unity": "hectares (ha)"}},
                {"age": "10-20", "amount": {"value": 8.0, "unity": "hectares (ha)"}},
                {"age": "20-30", "amount": {"value": 4.5, "unity": "hectares (ha)"}},
            ],
        },
        "vigor_stats": {
            "observation_year": 2024,
            "data": [
                {"vigor": "Baixo: pastagens com baixo vigor vegetativo", "amount": {"value": 5.0, "unity": "hectares (ha)"}},
                {"vigor": "Médio: pastagens com médio vigor vegetativo", "amount": {"value": 15.0, "unity": "hectares (ha)"}},
                {"vigor": "Alto: pastagens com alto vigor vegetativo", "amount": {"value": 5.0, "unity": "hectares (ha)"}},
            ],
        },
        "lulc_stats": {
            "observation_year": 2024,
            "data": [
                {"lulc_class": "Pastagem", "amount": {"value": 20.0, "unity": "hectares"}},
                {"lulc_class": "Formação Florestal", "amount": {"value": 3.0, "unity": "hectares"}},
                {"lulc_class": "Corpo D'água", "amount": {"value": 2.0, "unity": "hectares"}},
            ],
        },
    }


def _mock_topographic_stats_dict() -> dict:
    """Return a mocked TopographicStats.model_dump()-shaped dict."""
    return {
        "elevation": {"value": 612.5, "unity": "metros"},
        "slope": {"value": 5.2, "unity": "graus"},
    }


_PASTURE_STATS_TEMPLATE = """# RELATÓRIO AGROAMBIENTAL: ESTATÍSTICAS E ANÁLISE DE PASTAGENS
Este relatório descreve o estado atual, histórico e biológico das áreas monitoradas (piquete: {label}).

## 1. Produtividade Primária e Estoque de Carbono (Biomassa)
- Ano de Referência: 2026
- Estimativa de Massa Biológica Acumulada na Vegetação: 2340.5 tonelada(s) de matéria seca acumulada no mês
---
## 2. Histórico, Dinâmica Temporal e Idade da Pastagem
- Ano de Referência: 2024
- Distribuição da área territorial por tempo de existência da pastagem:
  * Faixa de idade contínua '1-10': 12.5 hectares (ha) de área coberta.
  * Faixa de idade contínua '10-20': 8.0 hectares (ha) de área coberta.
  * Faixa de idade contínua '20-30': 4.5 hectares (ha) de área coberta.
---
## 3. Qualidade Biológica e Performance Vegetativa Atual (Vigor)
- Ano de Referência: 2024
- Desempenho da performance vegetativa e vigor biológico atual:
  * Nível de vigor 'Baixo': 5.0 hectares (ha) de área territorial.
  * Nível de vigor 'Médio': 15.0 hectares (ha) de área territorial.
  * Nível de vigor 'Alto': 5.0 hectares (ha) de área territorial.
---
## 4. Cobertura do Solo e Integração de Paisagem (LULC)
- Ano de Referência: 2024
- Mapeamento detalhado de Uso e Cobertura da Terra (LULC):
  * Classe de uso/cobertura 'Pastagem': 20.0 hectares ocupados.
  * Classe de uso/cobertura 'Formação Florestal': 3.0 hectares ocupados.
  * Classe de uso/cobertura 'Corpo D'água': 2.0 hectares ocupados."""


# ── Forage budget ──────────────────────────────────────────────────────────

def get_forage_budget(args: dict) -> dict:
    """Mocked forage budget: estimates days of grass remaining.

    Combines pasture biomass + herd size to estimate how many days the
    current forage supply will last. Mocked — uses a fixed Cerrado-average
    biomass per hectare. See BENCHMARK.md.

    Parameters:
      - herd_size_ua : float (required) — herd size in Unidades Animais
      - car_codes : list[str] (optional) — property CAR codes
      - user_id : str (required)
    """
    herd_size_ua = args.get("herd_size_ua")
    if herd_size_ua is None:
        return {"error": "'herd_size_ua' é obrigatório (tamanho do rebanho em UA)."}
    try:
        herd_size_ua = float(herd_size_ua)
    except (TypeError, ValueError):
        return {"error": f"'herd_size_ua' deve ser numérico (recebido: {herd_size_ua!r})."}
    if herd_size_ua <= 0:
        return {"error": "'herd_size_ua' deve ser maior que zero."}

    state = _get_state(args.get("user_id", ""))
    all_props = state.get("all_properties", [])
    if all_props:
        area_ha = sum(p.get("spatial_features", {}).get("total_area", 100.0) for p in all_props)
    else:
        area_ha = 100.0

    total_biomass_kg = round(area_ha * 2500, 1)
    daily_consumption_kg = round(herd_size_ua * 450 * 0.025, 1)
    days_remaining = round(total_biomass_kg / daily_consumption_kg, 1)

    if days_remaining < 15:
        recommendation = "⚠️ Forragem crítica! Considere destocking imediato ou suplementação."
    elif days_remaining < 30:
        recommendation = "⚠️ Forragem baixa. Planeje redução do rebanho ou suplementação."
    elif days_remaining < 60:
        recommendation = "Forragem moderada. Monitore de perto nos próximos dias."
    else:
        recommendation = "✅ Forragem suficiente para o período."

    budget = {
        "area_ha": round(area_ha, 1),
        "total_biomass_kg": total_biomass_kg,
        "herd_size_ua": herd_size_ua,
        "daily_consumption_kg": daily_consumption_kg,
        "days_remaining": days_remaining,
        "recommendation": recommendation,
    }
    msg = (
        f"*Orçamento forrageiro*\n"
        f"Área: {budget['area_ha']} ha\n"
        f"Biomassa total: {budget['total_biomass_kg']} kg\n"
        f"Rebanho: {budget['herd_size_ua']} UA\n"
        f"Consumo diário: {budget['daily_consumption_kg']} kg/dia\n"
        f"Dias restantes: {budget['days_remaining']}\n"
        f"{recommendation}"
    )
    return {"message": msg, "forage_budget": budget}


# ── Paddock management ─────────────────────────────────────────────────────

def _find_paddock(paddocks: list, paddock_id: str) -> dict | None:
    """Find a paddock by id in the list."""
    for p in paddocks:
        if p.get("id") == paddock_id:
            return p
    return None


def auto_generate_paddocks(args: dict) -> dict:
    """Mocked auto-generation of paddocks for a property.

    Divides a property into N paddocks with varying areas. Stores them in
    session_state.all_paddocks. Mocked — uses property area from session or
    defaults to 100 ha. See BENCHMARK.md.

    Parameters:
      - car_codes : list[str] (required) — property CAR codes
      - count : int (optional, 2–10, default 4) — number of paddocks
      - user_id : str (required)
    """
    count = args.get("count", 4)
    try:
        count = int(count)
    except (TypeError, ValueError):
        return {"error": f"'count' deve ser inteiro (recebido: {count!r})."}
    if count < 2 or count > 10:
        return {"error": f"'count' deve estar entre 2 e 10 (recebido: {count})."}

    user_id = args.get("user_id", "")
    state = _get_state(user_id)
    all_props = state.get("all_properties", [])
    if all_props:
        total_area = sum(p.get("spatial_features", {}).get("total_area", 100.0) for p in all_props)
    else:
        total_area = 100.0

    base_area = total_area / count
    paddocks = []
    for i in range(1, count + 1):
        variance = 1.0 + ((i * 7) % 5 - 2) * 0.05
        area = round(base_area * variance, 1)
        paddocks.append({
            "id": f"pdk-{i:03d}",
            "label": f"Pasto {i}",
            "area_ha": area,
            "car_code": ", ".join(args.get("car_codes", [])) or "(propriedade atual)",
        })

    state["all_paddocks"] = paddocks
    _set_state(user_id, state)

    lines = [f"*{count} piquetes gerados automaticamente:*", ""]
    for p in paddocks:
        lines.append(f"• {p['id']} — {p['label']} ({p['area_ha']} ha)")
    lines.append("\nUse `set_paddock_label` para renomear cada piquete.")
    return {"message": "\n".join(lines), "paddocks": paddocks, "session_state": state}


def set_paddock_label(args: dict) -> dict:
    """Mocked set/update paddock label (rename).

    Parameters:
      - paddock_id : str (required) — paddock id (ex: pdk-001)
      - label : str (required) — new label/name
      - user_id : str (required)
    """
    paddock_id = args.get("paddock_id")
    label = args.get("label")
    if not paddock_id:
        return {"error": "'paddock_id' é obrigatório."}
    if not label:
        return {"error": "'label' é obrigatório."}

    user_id = args.get("user_id", "")
    state = _get_state(user_id)
    paddocks = state.get("all_paddocks", [])
    paddock = _find_paddock(paddocks, paddock_id)
    if not paddock:
        return {"error": f"Piquete '{paddock_id}' não encontrado. Use `auto_generate_paddocks` primeiro."}

    old_label = paddock["label"]
    paddock["label"] = label
    _set_state(user_id, state)

    return {
        "message": f"Piquete {paddock_id} renomeado de '{old_label}' para '{label}'.",
        "session_state": state,
    }


def delete_paddock(args: dict) -> dict:
    """Mocked delete a paddock by id.

    Parameters:
      - paddock_id : str (required) — paddock id (ex: pdk-001)
      - user_id : str (required)
    """
    paddock_id = args.get("paddock_id")
    if not paddock_id:
        return {"error": "'paddock_id' é obrigatório."}

    user_id = args.get("user_id", "")
    state = _get_state(user_id)
    paddocks = state.get("all_paddocks", [])
    paddock = _find_paddock(paddocks, paddock_id)
    if not paddock:
        return {"error": f"Piquete '{paddock_id}' não encontrado."}

    paddocks.remove(paddock)
    state["all_paddocks"] = paddocks
    _set_state(user_id, state)

    return {
        "message": f"Piquete {paddock_id} ('{paddock['label']}') removido.",
        "session_state": state,
    }


def get_paddock_pasture_stats(args: dict) -> dict:
    """Mocked per-paddock pasture stats (matches PastureStats schema shape).

    Parameters:
      - paddock_id : str (required)
      - user_id : str (required)
    """
    paddock_id = args.get("paddock_id")
    if not paddock_id:
        return {"error": "'paddock_id' é obrigatório."}
    user_id = args.get("user_id", "")
    state = _get_state(user_id)
    paddock = _find_paddock(state.get("all_paddocks", []), paddock_id)
    label = paddock["label"] if paddock else paddock_id
    stats = _mock_pasture_stats_dict(label)
    stats_text = _PASTURE_STATS_TEMPLATE.format(label=label)
    return {"stats_text": stats_text, "stats": stats}


def get_paddock_topographic_stats(args: dict) -> dict:
    """Mocked per-paddock topographic stats (matches TopographicStats shape).

    Parameters:
      - paddock_id : str (required)
      - user_id : str (required)
    """
    paddock_id = args.get("paddock_id")
    if not paddock_id:
        return {"error": "'paddock_id' é obrigatório."}
    stats = _mock_topographic_stats_dict()
    stats_text = (
        f"Topografia do piquete {paddock_id}:\n"
        f"Altitude: {stats['elevation']['value']} {stats['elevation']['unity']}\n"
        f"Declividade: {stats['slope']['value']} {stats['slope']['unity']}"
    )
    return {"stats_text": stats_text, "stats": stats}


def get_rotation_schedule(args: dict) -> dict:
    """Mocked rotational grazing schedule.

    Reads all_paddocks from session state (or mocks 4), assigns each a
    mocked biomass and days-since-last-graze, then orders by readiness.
    See BENCHMARK.md.

    Parameters:
      - rest_days : int (optional, default 30) — target rest period
      - herd_size_ua : float (optional) — herd size for occupancy calc
      - user_id : str (required)
    """
    rest_days = args.get("rest_days", 30)
    try:
        rest_days = int(rest_days)
    except (TypeError, ValueError):
        rest_days = 30
    herd_size_ua = args.get("herd_size_ua", 50)
    try:
        herd_size_ua = float(herd_size_ua)
    except (TypeError, ValueError):
        herd_size_ua = 50.0

    user_id = args.get("user_id", "")
    state = _get_state(user_id)
    paddocks = state.get("all_paddocks", [])
    if not paddocks:
        paddocks = [
            {"id": f"pdk-{i:03d}", "label": f"Pasto {i}", "area_ha": 25.0}
            for i in range(1, 5)
        ]

    schedule = []
    for i, p in enumerate(paddocks):
        biomass_kg_ha = 1800 + (i * 137) % 900
        days_since = (i * 11) % rest_days
        readiness = max(0, rest_days - days_since)
        occupancy_days = max(1, round(p["area_ha"] * biomass_kg_ha / (herd_size_ua * 450 * 0.025)))
        schedule.append({
            "paddock_id": p["id"],
            "label": p["label"],
            "biomass_kg_ha": biomass_kg_ha,
            "days_since_graze": days_since,
            "days_until_ready": readiness,
            "occupancy_days": occupancy_days,
        })
    schedule.sort(key=lambda s: s["days_until_ready"])

    lines = ["*Plano de rotação de pastagem*", ""]
    lines.append("Ordem | Piquete | Biomassa (kg/ha) | Dias em repouso | Pronto em | Ocupação (dias)")
    lines.append("-----|---------|-------------------|-----------------|-----------|----------------")
    for i, s in enumerate(schedule, 1):
        ready = "✅ pronto" if s["days_until_ready"] == 0 else f"{s['days_until_ready']} dias"
        lines.append(
            f"{i} | {s['label']} ({s['paddock_id']}) | {s['biomass_kg_ha']} | "
            f"{s['days_since_graze']} | {ready} | {s['occupancy_days']}"
        )
    return {"message": "\n".join(lines), "schedule": schedule}


# ── Vaccination calendar ───────────────────────────────────────────────────

_VACCINATION_CALENDAR = [
    {"month": 1,  "vaccine": "Raiva bovina",        "target": "Todo o rebanho",          "notes": "Endêmica no Centro-Oeste"},
    {"month": 3,  "vaccine": "Carbúnculo sintomático", "target": "Todo o rebanho",       "notes": "Reforço anual"},
    {"month": 5,  "vaccine": "Febre aftosa",        "target": "Todo o rebanho",          "notes": "1º semestre"},
    {"month": 5,  "vaccine": "Brucelose",           "target": "Fêmeas 3–8 meses",        "notes": "Dose única"},
    {"month": 7,  "vaccine": "Clostridioses",       "target": "Todo o rebanho",          "notes": "Reforço anual"},
    {"month": 11, "vaccine": "Febre aftosa",        "target": "Todo o rebanho",          "notes": "2º semestre"},
    {"month": 11, "vaccine": "Botulismo",           "target": "Todo o rebanho",          "notes": "Reforço anual"},
]

_MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def get_vaccination_calendar(args: dict) -> dict:
    """Mocked annual vaccination calendar (Cerrado/Centro-Oeste).

    Returns a fixed calendar with month, vaccine, target herd, and notes.
    Mocked — no real epidemiological data. See BENCHMARK.md.

    Parameters:
      - car_codes : list[str] (optional) — used to derive region
      - year : int (optional, default current year)
      - user_id : str (required)
    """
    year = args.get("year")
    if year is None:
        year = _dt.date.today().year  # noqa: DTZ011
    try:
        year = int(year)
    except (TypeError, ValueError):
        return {"error": f"'year' deve ser inteiro (recebido: {year!r})."}

    region = "Centro-Oeste"

    cal = [{**entry, "month_name": _MONTH_NAMES[entry["month"]], "year": year} for entry in _VACCINATION_CALENDAR]

    lines = [f"*Calendário de vacinação — {year} ({region})*", ""]
    lines.append("Mês | Vacina | Rebanho | Observações")
    lines.append("----|--------|---------|------------")
    for entry in cal:
        lines.append(f"{entry['month_name']} | {entry['vaccine']} | {entry['target']} | {entry['notes']}")
    lines.append("\n⚠️ Calendário de referência. Consulte um médico veterinário.")
    return {"message": "\n".join(lines), "calendar": cal}


# ── Action dispatch ────────────────────────────────────────────────────────

ACTIONS = {
    "request_biomass_alert": BiomassAlert.request,
    "confirm_biomass_alert": BiomassAlert.confirm,
    "request_rain_alert": RainAlert.request,
    "confirm_rain_alert": RainAlert.confirm,
    "request_vigor_alert": VigorAlert.request,
    "confirm_vigor_alert": VigorAlert.confirm,
    "request_stocking_rate_alert": StockingRateAlert.request,
    "confirm_stocking_rate_alert": StockingRateAlert.confirm,
    "list_schedulers": list_schedulers,
    "delete_scheduler": delete_scheduler,
    # weather-benchmark (mocked weather/rain data tools)
    "get_rain_forecast_15_days": get_rain_forecast_15_days,
    "get_rain_forecast_months": get_rain_forecast_months,
    "get_rain_history": get_rain_history,
    "get_weather_today": get_weather_today,
    "get_temperature_forecast_15_days": get_temperature_forecast_15_days,
    "get_drought_index": get_drought_index,
    "get_evapotranspiration": get_evapotranspiration,
    "get_soil_moisture": get_soil_moisture,
    "get_climate_summary": get_climate_summary,
    # pasture-benchmark / paddock-benchmark / herd-benchmark
    "get_forage_budget": get_forage_budget,
    "auto_generate_paddocks": auto_generate_paddocks,
    "set_paddock_label": set_paddock_label,
    "delete_paddock": delete_paddock,
    "get_paddock_pasture_stats": get_paddock_pasture_stats,
    "get_paddock_topographic_stats": get_paddock_topographic_stats,
    "get_rotation_schedule": get_rotation_schedule,
    "get_vaccination_calendar": get_vaccination_calendar,
}


# ── CLI entry (identical contract to feedback.py / property.py) ───────────

if __name__ == "__main__":
    args = json.loads(base64.b64decode(sys.argv[1]))
    action = args.pop("action")
    fn = ACTIONS.get(action)
    if not fn:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)
    try:
        result = fn(args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))