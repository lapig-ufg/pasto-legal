import re
from datetime import datetime

from agno.tools import tool
from agno.run import RunContext

from app.database.session import SessionLocal, engine
from app.database.models import FrustrationFeedback, AnalysisFeedback


def _mask_pii(text: str) -> str:
    if not text:
        return ""
        
    patterns = {
        'CPF': re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
        'CNPJ': re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"),
        'CAR': re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9.]+\b", re.IGNORECASE),
        'COORDINATES': re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})")
    }

    masked_text = str(text)
    for label, pattern in patterns.items():
        masked_text = pattern.sub(f"[{label}_OCULTO]", masked_text)
        
    return masked_text


@tool
def record_frustration_feedback(
    original_question: str, 
    reason_frustration: str, 
    desired_answer: str,
    run_context: RunContext = None
) -> str:
    """
    Registra uma correção do usuário quando o assistente fornece uma resposta incorreta.

    REGRAS CRÍTICAS DE PRIVACIDADE (LGPD):
    Antes de chamar esta ferramenta, você DEVE anonimizar todos os parâmetros (original_question, reason_frustration, desired_answer).
    - Substitua nomes de pessoas por [NOME_USUARIO].
    - Substitua nomes de propriedades/fazendas por [NOME_FAZENDA].
    - Substitua números de CAR por [CAR_OCULTO].
    - Substitua coordenadas geográficas por [COORDENADAS_OCULTAS].
    - Substitua CPFs/CNPJs por [DOCUMENTO_OCULTO].
    
    Use esta função estritamente quando a seguinte sequência de eventos ocorrer:
    1. O usuário faz uma pergunta.
    2. O assistente responde.
    3. O usuário reclama da resposta (ex: "não era isso", "está errado").
    4. O assistente pede para o usuário explicar como seria a resposta correta.
    5. O usuário fornece a resposta ou correção esperada.

    Args:
        original_question (str): A pergunta inicial anonimizada.
        reason_frustration (str): O motivo do erro com dados sensíveis mascarados.
        desired_answer (str): A resposta esperada com dados sensíveis mascarados.
    """
    FrustrationFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    try:
        
        historico_str = ""
        if run_context and run_context.messages:
            ultimas_mensagens = run_context.messages[-3:]
            historico_str = "\n".join([f"{m.role}: {m.content}" for m in ultimas_mensagens])

        novo_feedback = FrustrationFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(original_question),
            reason_frustration=_mask_pii(reason_frustration),
            desired_answer=_mask_pii(desired_answer),
            context=_mask_pii(historico_str)
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
def record_analisys_feedback(
    original_question: str, 
    desired_analysis: str,
    run_context: RunContext = None
) -> str:
    """
    Registra uma sugestão de nova funcionalidade ou análise de dados.
    
    Use esta função estritamente quando a seguinte sequência ocorrer:
    1. O usuário solicita uma análise de dados, cruzamento de informações ou relatório específico.
    2. O assistente não possui as ferramentas ou capacidades para gerar essa análise.
    3. O usuário descreve como seria a estrutura ou o resultado ideal dessa análise.

    REGRAS CRÍTICAS DE PRIVACIDADE (LGPD):
    Antes de chamar esta ferramenta, você DEVE anonimizar os parâmetros (original_question, desired_analysis).
    - Substitua referências a locais específicos, nomes próprios, números de CAR ou coordenadas por tags genéricas (ex: [NOME_FAZENDA], [CAR_OCULTO], [COORDENADAS_OCULTAS]).
    
    Args:
        original_question (str): A solicitação inicial anonimizada.
        desired_analysis (str): A descrição da análise com dados sensíveis mascarados.
    """
    AnalysisFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    try:
        historico_str = ""
        if run_context and run_context.messages:
            ultimas_mensagens = run_context.messages[-3:]
            historico_str = "\n".join([f"{m.role}: {m.content}" for m in ultimas_mensagens])

        novo_feedback = AnalysisFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(original_question),
            desired_analysis=_mask_pii(desired_analysis),
            context=_mask_pii(historico_str)
        )
        
        db.add(novo_feedback)
        db.commit()
        
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    
    except Exception as e:
        db.rollback()
        return f"Erro ao registrar feedback: {str(e)}"
    
    finally:
        db.close()