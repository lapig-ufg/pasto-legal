"""
CLI wrapper for feedback collection (frustration remediation loop).

Two actions:
  - request_feedback : sets session_state.feedback_mode="awaiting_rating"
  - save_feedback    : persists positive/negative feedback to the database
                       and clears feedback_mode

Called by pi's bash tool via the pi subprocess extension.

Usage:
  python agent/tools/feedback.py '<base64-json-args>'
"""
import base64
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_PII_PATTERNS = {
    "CPF": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "CNPJ": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"),
    "CAR": re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9.]+\b", re.IGNORECASE),
    "COORDINATES": re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})"),
}


def _mask_pii(text: str) -> str:
    if not text:
        return ""
    masked = str(text)
    for label, pattern in _PII_PATTERNS.items():
        masked = pattern.sub(f"[{label}_OCULTO]", masked)
    return masked


def request_feedback(args: dict) -> dict:
    return {
        "message": (
            "Modo de feedback ativado. Aguardando a avaliação do usuário "
            "sobre a resposta reformulada."
        ),
        "session_state": {"feedback_mode": "awaiting_rating"},
    }


def save_feedback(args: dict) -> dict:
    from api.database.models import NegativeFeedback, PositiveFeedback
    from api.database.session import SessionLocal, engine

    verdict = args["verdict"]
    user_message = args.get("user_message", "")
    assistant_response = args.get("assistant_response", "")
    reason = args.get("reason", "")

    timestamp = datetime.datetime.utcnow().isoformat()
    masked_user = _mask_pii(user_message)
    masked_response = _mask_pii(assistant_response)
    masked_reason = _mask_pii(reason)

    session_state_update = {"feedback_mode": None}

    db = SessionLocal()
    try:
        if verdict == "positive":
            PositiveFeedback.metadata.create_all(bind=engine)
            record = PositiveFeedback(
                timestamp=timestamp,
                user_message=masked_user,
                assistant_response=masked_response,
                handler_message=masked_reason,
                grade=5,
                context=masked_response,
            )
            db.add(record)
            db.commit()
            return {
                "message": "Feedback positivo registrado. Obrigado!",
                "session_state": session_state_update,
            }
        elif verdict == "negative":
            NegativeFeedback.metadata.create_all(bind=engine)
            record = NegativeFeedback(
                timestamp=timestamp,
                original_question=masked_user,
                reason_frustration=masked_reason,
                desired_answer=masked_response,
                context=masked_response,
            )
            db.add(record)
            db.commit()
            return {
                "message": "Feedback negativo registrado. Pedimos desculpas.",
                "session_state": session_state_update,
            }
        else:
            return {
                "error": f"Unknown verdict: {verdict}. Use 'positive' or 'negative'.",
                "session_state": session_state_update,
            }
    except Exception as e:
        db.rollback()
        return {"error": str(e), "session_state": session_state_update}
    finally:
        db.close()


ACTIONS = {
    "request_feedback": request_feedback,
    "save_feedback": save_feedback,
}

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