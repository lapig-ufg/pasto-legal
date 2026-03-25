import streamlit as st

from datetime import datetime

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