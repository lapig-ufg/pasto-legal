from datetime import datetime

from agno.tools import tool

from app.database.session import SessionLocal, engine
from app.database.models import Feedback


@tool
def record_feedback(original_question: str, reason_frustration: str, desired_answer: str) -> str:
    """
    Registra o feedback de correção do usuário no banco de dados para melhorar a IA no futuro.
    Use esta ferramenta SEMPRE que o usuário demonstrar frustração com uma resposta,
    informando que a resposta foi ruim, incorreta ou inútil, e após você perguntar
    e ele fornecer a resposta esperada.

    Args:
        original_question (str): A pergunta ou requisição inicial do usuário que gerou a frustração.
        reason_frustration (str): O motivo pelo qual o usuário não gostou da resposta anterior.
        desired_answer (str): A resposta ideal ou a correção que o usuário forneceu para nos ensinar.
    """
    Feedback.metadata.create_all(bind=engine)

    db = SessionLocal()
    
    try:
        novo_feedback = Feedback(
            timestamp=datetime.now().isoformat(),
            pergunta_original=original_question,
            motivo_frustracao=reason_frustration,
            resposta_desejada=desired_answer
        )
        
        db.add(novo_feedback)
        db.commit()
        
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    
    except Exception as e:
        db.rollback()
        return f"Erro ao registrar feedback: {str(e)}"
    
    finally:
        db.close()