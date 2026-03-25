import streamlit as st

from src.service import get_runs_by_session_id

def render_chat_panel(col):
    if not 'selected_session_id' in st.session_state:
        return

    # TODO: Seleção dinâmica da quantidade de runs para exibir.
    runs = get_runs_by_session_id(st.session_state.selected_session_id)

    with col:
        st.caption(f"Sessão ID: wa:{st.session_state.selected_session_id}")
        
        chat_container = st.container(height='stretch')
        
        with chat_container:
            for run in runs:
                with st.chat_message('user'):
                    st.write(run.input.input_content)
                
                with st.chat_message('assistant'):
                    st.write(run.content)

                    if st.button("+", key=run.run_id):
                        st.session_state.selected_run = run