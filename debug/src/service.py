import streamlit as st

from agno.agent import RunOutput

from src.database.session import SessionLocal
from src.database.models import AgentSession

@st.cache_data
def get_all_session_ids() -> list[str]:
    """
    Retorna uma lista com todos os session_ids cadastrados no banco.
    """
    with SessionLocal() as db:
        resultados = db.query(AgentSession.session_id).all()
        return [None] + [linha[0] for linha in resultados]

@st.cache_data
def get_runs_by_session_id_v2(session_id: str, n_messages: int, timestamp: int) -> list[RunOutput]:
    """
    Função bônus: Retorna os dados de run de uma sessão específica.
    Muito útil para quando você clicar no botão do sidebar no Streamlit.
    """
    print("Hello WOrld")
    with SessionLocal() as db:
        raw = db.query(AgentSession.runs).filter(AgentSession.session_id == session_id).first()

        if not raw or not raw[0]:
            return None
        
        run_map: dict[str, RunOutput] = {}
        for element in raw[0]:
            run = RunOutput.from_dict(element)
            run.childs = []
            run_map[run.run_id] = run

        root_runs: list[RunOutput] = []
        for run in run_map.values():
            if run.parent_run_id and run.parent_run_id in run_map:
                parent = run_map[run.parent_run_id]
                parent.childs.append(run)
            else:
                root_runs.append(run)

        return root_runs[-n_messages:]