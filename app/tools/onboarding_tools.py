import datetime
from agno.tools import tool
from agno.run import RunContext

from app.database.session import SessionLocal, engine 
from app.database.models import UserTermsAcceptance

@tool
def accept_terms_and_conditions(run_context: RunContext) -> str:
    """
    Records the user's formal acceptance of the Pasto Legal Terms and Conditions in the database.
    """
    session_state = run_context.session_state or {}
    user_id = run_context.user_id or session_state.get("user_id")
    
    if not user_id:
        return "Error: User identifier not found in the execution context."

    
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
        
        session_state["terms_accepted"] = True
        session_state["terms_accepted_at"] = now.isoformat()
        
        return "Formal acceptance successfully registered! The main workflow has been unlocked. Politely inform the user."
    except Exception as e:
        db.rollback()
        return f"Critical persistence error while saving terms acceptance: {str(e)}"
    finally:
        db.close()