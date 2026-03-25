import streamlit as st

from src.components import render_chat_panel, render_debug_panel, render_sidebar

def main():
    st.set_page_config(page_title="WhatsApp Agent Debbuger", layout="wide")

    if "selected_session_id" not in st.session_state:
        st.session_state.selected_session_id = None

    if "selected_run" not in st.session_state:
        st.session_state.selected_run = None

    render_sidebar()
    
    chat_col, debug_col = st.columns(2)
    
    render_chat_panel(chat_col)
    render_debug_panel(debug_col)

if __name__ == "__main__":
    main()