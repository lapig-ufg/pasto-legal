import datetime
from agno.tools import tool
from agno.run import RunContext
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description
from app.database.session import SessionLocal, engine 
from app.database.models import UserTermsAcceptance

@tool(description=get_tool_description("onboarding_tools", "accept_terms_and_conditions"))
def accept_terms_and_conditions(run_context: RunContext) -> str:
    """
    Records the user's formal acceptance of the Pasto Legal Terms and Conditions in the database.
    """
    log_debug("accept_terms_and_conditions: iniciando")
    session_state = run_context.session_state or {}
    user_id = run_context.user_id or session_state.get("user_id")
    
    if not user_id:
        log_warning("accept_terms_and_conditions: user_id ausente no contexto")
        return "Error: User identifier not found in the execution context."

    
    UserTermsAcceptance.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        log_debug(f"accept_terms_and_conditions: registrando aceite para user_id={user_id}")
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
        
        log_debug(f"accept_terms_and_conditions: aceite registrado para user_id={user_id}")
        return "Formal acceptance successfully registered! The main workflow has been unlocked. Politely inform the user."
    except Exception as e:
        db.rollback()
        log_error(f"accept_terms_and_conditions: erro de persistência para user_id={user_id}: {e}")
        return f"Critical persistence error while saving terms acceptance: {str(e)}"
    finally:
        db.close()