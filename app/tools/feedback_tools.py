from datetime import datetime

from agno.tools import tool

from app.database.session import SessionLocal, engine
from app.database.models import FrustrationFeedback, AnalysisFeedback


@tool
def record_frustration_feedback(original_question: str, reason_frustration: str, desired_answer: str) -> str:
    """
    Registra uma correção do usuário quando o assistente fornece uma resposta incorreta, inútil ou de baixa qualidade.
    
    Use esta função estritamente quando a seguinte sequência de eventos ocorrer:
    1. O usuário faz uma pergunta.
    2. O assistente responde.
    3. O usuário reclama da resposta (ex: "não era isso", "está errado").
    4. O assistente pede para o usuário explicar como seria a resposta correta.
    5. O usuário fornece a resposta ou correção esperada.

    Args:
        original_question (str): A pergunta inicial exata do usuário que o assistente falhou em responder adequadamente.
        reason_frustration (str): O motivo do erro segundo o usuário (ex: "cálculo errado", "resposta genérica demais", "dados desatualizados").
        desired_answer (str): A resposta correta e detalhada que o usuário informou que gostaria de ter recebido.
    """
    FrustrationFeedback.metadata.create_all(bind=engine)

    db = SessionLocal()
    
    try:
        novo_feedback = FrustrationFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=original_question,
            reason_frustration=reason_frustration,
            desired_answer=desired_answer
        )
        
        db.add(novo_feedback)
        db.commit()
        
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    
    except Exception as e:
        db.rollback()
        return f"Erro ao registrar feedback: {str(e)}"
    
    finally:
        db.close()

@tool
def record_analisys_feedback(original_question: str, desired_analysis: str) -> str:
    """
    Registra uma sugestão de nova funcionalidade quando o usuário pede um tipo de análise que o assistente ainda não consegue realizar.
    
    Use esta função estritamente quando a seguinte sequência ocorrer:
    1. O usuário solicita uma análise de dados, cruzamento de informações ou relatório específico.
    2. O assistente não possui as ferramentas ou capacidades para gerar essa análise.
    3. O usuário descreve como seria a estrutura ou o resultado ideal dessa análise.

    Args:
        original_question (str): A solicitação inicial do usuário pedindo a análise que o sistema não conseguiu fazer.
        desired_analisys (str): A descrição detalhada feita pelo usuário de como a análise deveria funcionar, quais métricas deveria conter ou qual seria o formato ideal do resultado.
    """
    AnalysisFeedback.metadata.create_all(bind=engine)

    db = SessionLocal()
    
    try:
        novo_feedback = AnalysisFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=original_question,
            desired_analysis=desired_analysis
        )
        
        db.add(novo_feedback)
        db.commit()
        
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    
    except Exception as e:
        db.rollback()
        return f"Erro ao registrar feedback: {str(e)}"
    
    finally:
        db.close()