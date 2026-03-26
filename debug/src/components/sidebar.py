import time
import streamlit as st

from src.service import get_all_session_ids

def render_sidebar():
    with st.sidebar:
        session_ids = get_all_session_ids()

        st.header("Sessões Ativas")
        st.session_state.selected_session_id = st.selectbox('IDs das sessões', session_ids)
        
        st.divider()
        st.subheader("Filtros")
        st.selectbox("Status", ["Todos", "Aguardando", "Erro", "Completos"])

        st.divider()
        is_refresh = st.button("Atualizar")
        if is_refresh:
            st.session_state.timestamp = time.time()