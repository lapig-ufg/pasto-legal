import json
import streamlit as st

from itertools import islice
from datetime import datetime
from agno.agent import RunOutput

def render_debug_panel(col):
    with col:
        with st.container(height=750, key='right-container'):
            if not st.session_state.selected_run:
                st.text("Nada para inspecionar... 🔍", text_alignment='center', width='stretch')
                return
            
            run: RunOutput = st.session_state.selected_run

            tabs = st.tabs(["Run Graph", "Session State", ["JSON"]])

            with tabs[0]:
                disable_from_hitory = st.toggle("Filter by is_from_history.", value=False)

                _messages = run.messages
                for idx, message in enumerate(_messages):
                    if disable_from_hitory and message.from_history:
                        continue

                    match message.role:
                        case 'user':
                            with st.expander(f"{':red_circle:' if message.from_history else ':large_blue_circle:'} Usuário", expanded=False):
                                data_obj = datetime.fromtimestamp(message.created_at)
                                data_formatted = data_obj.strftime('%d/%m/%Y %H:%M:%S')
                                st.caption(f"**Data:** {data_formatted}")
                                
                                with st.container(width='stretch', height='content', border=True):
                                    st.caption("Content:")
                                    st.text(message.content, width='stretch')
                
                        case 'assistant':
                            with st.expander(":cow: Assistente", expanded=False):
                                st.caption(f"**Name**: {message.name}")

                                data_obj = datetime.fromtimestamp(message.created_at)
                                data_formatted = data_obj.strftime('%d/%m/%Y %H:%M:%S')
                                st.caption(f"**Data:** {data_formatted}")
                                
                                with st.container(width='stretch', height='content', border=True):
                                    st.caption("Content:")
                                    st.text(message.content, width='stretch')
                                
                                tabs = st.tabs(["Tool Calls"])
                                with tabs[0]:
                                    if not message.tool_calls:
                                        st.text("No tool calls...")
                                        continue

                                    for tool_call in message.tool_calls:
                                        if tool_call["type"] == "function":
                                            _function = tool_call["function"]
                                                        
                                            with st.expander(f"{_function["name"]}", expanded=False):
                                                _tool_call = next(
                                                    (_message for _message in islice(_messages, idx + 1, None)
                                                    if _message.tool_calls and _message.tool_calls[0].get("tool_call_id", None) == tool_call["id"]),
                                                    None
                                                )

                                                data_obj = datetime.fromtimestamp(_tool_call.created_at)
                                                data_formatted = data_obj.strftime('%d/%m/%Y %H:%M:%S')
                                                st.caption(f"**Data:** {data_formatted}")

                                                with st.container(width='stretch', height='content', border=True):
                                                    st.caption("Arguments:")
                                                    st.json(json.loads(_function["arguments"]), width='stretch')

                                                with st.container(width='stretch', height='content', border=True):
                                                    st.caption("Result:")
                                                    st.json(_tool_call.content, width='stretch')

                        case 'system':
                            with st.expander(":streamlit: System", expanded=False):
                                data_obj = datetime.fromtimestamp(message.created_at)
                                data_formatted = data_obj.strftime('%d/%m/%Y %H:%M:%S')
                                st.caption(f"**Data:** {data_formatted}")

                                with st.container(width='stretch', height='content', border=True):
                                    st.caption("Instruction:")
                                    st.json(message.content, width='stretch')
                
                st.info("**Resposta Final**")
                with st.expander("Ver JSON Completo da Execução"):
                    st.json(run.to_json())
            
            with tabs[1]:
                st.json(run.session_state)