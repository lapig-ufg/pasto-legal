import streamlit as st

from agno.agent import RunOutput
from typing import List

from src.service import get_runs_by_session_id

def render_chat_panel(col, n_messages):
    if not 'selected_session_id' in st.session_state:
        return

    runs: List[RunOutput] = get_runs_by_session_id(st.session_state.selected_session_id, n_messages)

    with col:
        st.caption(f"Sessão ID: wa:{st.session_state.selected_session_id}")
        
        with st.container(height=800, border=True):
            for run in runs:
                with st.chat_message('user'):
                    st.write(run.input.input_content)
                
                with st.chat_message('assistant'):
                    st.write(run.content)

                    if st.button("+", key=run.run_id):
                        st.session_state.selected_run = run