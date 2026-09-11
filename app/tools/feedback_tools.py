import re
from datetime import datetime
from agno.tools import tool
from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description
from app.database.session import SessionLocal, engine
from app.database.models import NegativeFeedback, AnalysisFeedback

def _mask_pii(text: str) -> str:
    """ Fallback Determinístico: Mascara dados sensíveis usando Regex """
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

def _get_sanitized_history(run_context: RunContext) -> str:
    """ Função auxiliar: Filtra as últimas 3 interações limpas e passa pelo sanitizador semântico """
    if not run_context.messages:
        return ""
        
    history = []
    user_msg_count = 0

    # 1. Filtro de Histórico Real (Ignora lixo e para na 3ª msg do user)
    for msg in reversed(run_context.messages):
        if user_msg_count == 3:
            break

        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")

        if role in ["user", "assistant"]:
            history.append(f"{role.upper()}: {content}")
            if role == "user":
                user_msg_count += 1

    history_text = "\n".join(history[::-1])

    # 2. Agente Sanitizador In-Line (Camada 1 - IA)
    if not history_text:
        return ""
        
    sanitizer_agent = Agent(
        model=Gemini(id="gemini-3-flash-preview", temperature=0),
        description=(
            "Você é um filtro de privacidade estrito. Leia a transcrição e reescreva semanticamente os dados, "
            "substituindo nomes próprios de pessoas, cidades e propriedades rurais por tags genéricas "
            "(como [USUARIO], [MUNICIPIO], [FAZENDA]). MANTENHA TODO O CONTEXTO AGRONÔMICO INTACTO."
        )
    )
    
    try:
        sanitizer_response = sanitizer_agent.run(history_text)
        sanitized_history = sanitizer_response.content if sanitizer_response and sanitizer_response.content else history_text
    except Exception as sanitizer_error:
        log_warning(f"Sanitizador semântico falhou, usando fallback determinístico: {sanitizer_error}")
        sanitized_history = history_text
        
    # 3. Fallback Determinístico (Camada 2 - Regex)
    return _mask_pii(sanitized_history)

@tool(description=get_tool_description("feedback_tools", "record_frustration_feedback"))
def record_frustration_feedback(
    reason_frustration: str, 
    desired_answer: str,
    run_context: RunContext = None
) -> str:
    """
    Registra uma correção do usuário quando o assistente fornece uma resposta incorreta.
    Use esta função estritamente quando a seguinte sequência de eventos ocorrer:
    1. O usuário faz uma pergunta.
    2. O assistente responde.
    3. O usuário reclama da resposta.
    4. O assistente pede para o usuário explicar como seria a resposta correta.
    5. O usuário fornece a resposta.
    """
    NegativeFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    log_debug("record_frustration_feedback: iniciando registro")
    try:
        # Puxa o histórico já limpo e anonimizado pela nossa esteira
        sanitized_history = _get_sanitized_history(run_context)
        
        novo_feedback = NegativeFeedback(
            timestamp=datetime.now().isoformat(),
            original_question="",
            reason_frustration=_mask_pii(reason_frustration),
            desired_answer=_mask_pii(desired_answer),
            context=sanitized_history
        )
        
        db.add(novo_feedback)
        db.commit()
        log_debug("record_frustration_feedback: feedback registrado com sucesso")
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    except Exception as e:
        db.rollback()
        log_error(f"record_frustration_feedback: erro ao registrar feedback: {e}")
        return f"Erro ao registrar feedback: {str(e)}"
    finally:
        db.close()

@tool(description=get_tool_description("feedback_tools", "record_analisys_feedback"))
def record_analisys_feedback(
    original_question: str, 
    desired_analysis: str,
    run_context: RunContext = None
) -> str:
    """
    Registra uma sugestão de nova funcionalidade ou análise de dados.
    Use quando o usuário solicitar uma análise que o assistente ainda não possui ferramentas para gerar.
    """
    AnalysisFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    log_debug("record_analisys_feedback: iniciando registro")
    try:
        # Puxa o histórico já limpo e anonimizado pela nossa esteira
        final_safe_context = _get_sanitized_history(run_context)
        
        novo_feedback = AnalysisFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(original_question),
            desired_analysis=_mask_pii(desired_analysis),
            context=final_safe_context
        )
        
        db.add(novo_feedback)
        db.commit()
        log_debug("record_analisys_feedback: feedback registrado com sucesso")
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    except Exception as e:
        db.rollback()
        log_error(f"record_analisys_feedback: erro ao registrar feedback: {e}")
        return f"Erro ao registrar feedback: {str(e)}"
    finally:
        db.close()