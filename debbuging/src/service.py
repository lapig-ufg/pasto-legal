import streamlit as st

from src.database.session import SessionLocal
from src.database.models import AgentSession

@st.cache_data
def get_all_session_ids() -> list[str]:
    """
    Retorna uma lista com todos os session_ids cadastrados no banco.
    """
    with SessionLocal() as db:
        resultados = db.query(AgentSession.session_id).all()
        return [linha[0] for linha in resultados]

def get_all_runs() -> list[dict]:
    """
    Retorna uma lista com os estados/runs de todas as sessões.
    Ideal para resgatar o histórico de JSONs para o seu debug visual no Streamlit.
    """
    with SessionLocal() as db:
        resultados = db.query(AgentSession.runs).all()
        return [linha[0] for linha in resultados if linha[0] is not None]

@st.cache_data
def get_runs_by_session_id(session_id: str) -> dict | None:
    """
    Função bônus: Retorna os dados de run de uma sessão específica.
    Muito útil para quando você clicar no botão do sidebar no Streamlit.
    """
    with SessionLocal() as db:
        resultado = db.query(AgentSession.runs).filter(AgentSession.session_id == session_id).first()
        
        if resultado:
            return resultado[0]
        return None