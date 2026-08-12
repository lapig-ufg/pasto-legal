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