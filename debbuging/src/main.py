import streamlit as st

from datetime import datetime

from src.service import get_all_session_ids, get_runs_by_session_id

st.set_page_config(page_title="WhatsApp Agent Debbuger", layout="wide")

if "selected_session_id" not in st.session_state:
    st.session_state.selected_session_id = None

if "selected_run" not in st.session_state:
    st.session_state.selected_run = None

# ==========================================
# 1. COLUNA 1: SIDEBAR (Esquerda)
# ==========================================
def render_sidebar():
    with st.sidebar:
        session_ids = get_all_session_ids()

        st.header("Sessões Ativas")
        st.session_state.selected_session_id = st.selectbox('IDs das sessões', session_ids)
        
        st.divider()
        st.subheader("Filtros")
        st.selectbox("Status", ["Todos", "Aguardando", "Erro", "Completos"])

# ==========================================
# 3. COLUNA 2: CHAT (Meio)
# ==========================================
def render_chat(col):
    if not 'selected_session_id' in st.session_state:
        return

    # TODO: Seleção dinâmica da quantidade de runs para exibir.
    runs = get_runs_by_session_id(st.session_state.selected_session_id)[:-15]

    with col:
        st.caption(f"Sessão ID: wa:{st.session_state.selected_session_id}")
        
        chat_container = st.container(height=800)
        
        with chat_container:
            for run in runs:
                with st.chat_message('user'):
                    if 'input' in run:
                        st.write(run['input']['input_content'])
                
                with st.chat_message('assistant'):
                    st.write(run['content'])

                    if st.button("🔍 Inspecionar Fluxo", key=run["run_id"]):
                        st.session_state.selected_run = run

# ==========================================
# 4. COLUNA 3: INFORMAÇÕES/DEBUG (Direita)
# ==========================================
def render_debug_panel(col):
    with col:
        if not st.session_state.selected_run:
            st.info("Selecione '🔍 Inspecionar Fluxo' em uma mensagem para ver os detalhes da execução.")
            return

        data = st.session_state.selected_run

        tab1, tab2, tab3 = st.tabs(["Fluxo de Execução", "Etado Final da Sessão", "Métricas"], width="stretch")

        with tab1:
            st.subheader("Fluxo de Execução")

            for msg in data['messages']:
                match msg['role']:
                    case 'user':
                        is_from_history = msg['from_history']

                        with st.expander(f"{':red_circle:' if is_from_history else ':large_blue_circle:'} Usuário", expanded=False):
                            data_obj = datetime.fromtimestamp(msg['created_at'])
                            data_formatted = data_obj.strftime('%d/%m/%Y %H:%M:%S')
                            st.caption(f"**Data:** {data_formatted}")
                            
                            st.write("**Entrada:**")
                            with st.container(width='stretch', height='content', border=True):
                                st.text(msg['content'])
            
                    case 'assistant':
                        with st.expander("🤖 Assistente", expanded=False):
                            st.caption(f"**Modelo:** {data['model']}")
                            
                            st.write("**Ação Tomada:**")
                            st.code("Analisou a intenção do usuário e respondeu diretamente, pois era uma saudação/pedido de apresentação geral.", language="text")
                            
                            tabs = st.tabs(["Contexto Injetado", "Tool Calls (Mock)"])
                            with tabs[0]:
                                st.write("*System prompt com as instruções do coordenador carregado.*")
                            with tabs[1]:
                                st.info("Nenhuma ferramenta foi chamada nesta iteração.")
                    case 'tool':
                        pass
                    case 'system':
                        pass

                st.markdown("<h2 style='text-align: center;'>&#8595</h2>", unsafe_allow_html=True)
            
            st.info("**Resposta Final**")
            with st.expander("Ver JSON Completo da Execução"):
                st.json(data)

        with tab2:
            st.text("Hello, World!")

        with tab3:
            st.text("Goodbye, World!")

# ==========================================
# FUNÇÃO PRINCIPAL
# ==========================================
def main():
    render_sidebar()
    
    chat_col, debug_col = st.columns(2)
    
    render_chat(chat_col)
    render_debug_panel(debug_col)

if __name__ == "__main__":
    main()