"""
CLI wrapper for onboarding (terms acceptance).
Called by pi's bash tool via the pi subprocess extension.

Usage:
  python cli/onboarding.py '<base64-json-args>'
"""
import sys
import json
import os
import base64
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def accept_terms(args: dict) -> dict:
    from app.database.session import SessionLocal, engine
    from app.database.models import UserTermsAcceptance

    user_id = args["user_id"]
    UserTermsAcceptance.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        record = db.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == user_id).first()
        now = datetime.datetime.utcnow()
        if not record:
            record = UserTermsAcceptance(user_id=user_id, accepted=True, accepted_at=now)
            db.add(record)
        else:
            record.accepted = True
            record.accepted_at = now
        db.commit()
        return {
            "message": "Termos de Uso aceitos! 🎉 O sistema está liberado para uso. Como posso ajudar?",
            "session_state": {"terms_accepted": True, "terms_accepted_at": now.isoformat()},
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


ACTIONS = {"accept_terms": accept_terms}

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
