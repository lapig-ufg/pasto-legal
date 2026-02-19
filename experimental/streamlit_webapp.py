import os
import uuid
import json
import redis
import pickle
import tempfile
import streamlit as st
import requests

from typing import List

from agno.tools.function import UserInputField

from app.agents.easter_egg_agent import easter_egg_agent
from app.agents.main_team import pasto_legal_team

st.set_page_config(page_title="Pasto Legal", page_icon="🐂")

DB_FILE = "users_db.json"

# ==================== BANCO DE DADOS ====================

def get_users():
    if not os.path.exists(DB_FILE):
        return []
    
    try:
        with open(DB_FILE, "r") as file:
            return json.load(file)
    except:
        return []

def new_user(user_id, user_name):
    users = get_users()

    if not any(user['id'] == user_id for user in users):
        users.append({"id": user_id, "name": user_name})
        with open(DB_FILE, "w") as f:
            json.dump(users, f, indent=4)

def login_user(user_id, user_name="Anônimo"):
    st.session_state["session_id"] = user_id
    st.session_state["user_name"] = user_name
    st.session_state["logged_in"] = True
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    st.rerun()

def logout():
    st.session_state["logged_in"] = False
    st.session_state["session_id"] = None
    st.session_state["user_name"] = None
    st.session_state["messages"] = []

    st.rerun()

# ==================== TELA DE LOGIN ====================

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("🔐 Login - Pasto Legal")

    col1, col2, col3 = st.columns(3)

    # 1. Lista de Usuários Armazenados
    with col1:
        st.subheader("📂 Histórico")
        stored_users = get_users()
        
        if stored_users:
            selected_obj = st.selectbox(
                "Escolha o usuário:", 
                stored_users, 
                format_func=lambda x: x['name']
            )
            
            if st.button("Entrar"):
                login_user(selected_obj['id'], selected_obj['name'])
        else:
            st.info("Vazio")

    # 2. Criar Novo Usuário (Com Nome)
    with col2:
        st.subheader("🆕 Novo")
        new_name_input = st.text_input("Identificação do usuário")
        
        if st.button("Criar"):
            if new_name_input.strip():
                new_id = str(uuid.uuid4())
                new_user(new_id, new_name_input)
                login_user(new_id, new_name_input)
            else:
                st.warning("Por favor, digite um nome para salvar.")

    # 3. Entrar Anonimamente
    with col3:
        st.subheader("🕵️ Anônimo")
        if st.button("Entrar Anonimamente"):
            anon_id = str(uuid.uuid4())
            login_user(anon_id, "Visitante Anônimo")

    st.stop()

# ==========================================
# APLICAÇÃO PRINCIPAL (CHAT)
# ==========================================

with st.sidebar:
    st.write(f"👤 **Usuário:** {st.session_state.get('user_name', 'Desconhecido')}")
    st.caption(f"ID: {st.session_state['session_id']}")
    st.divider()
    if st.button("Sair / Trocar Usuário"):
        logout()

st.title(f"🐂 Olá, {st.session_state.get('user_name', '')}")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Exibe mensagens anteriores
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Inputs do usuário
files_uploaded = st.file_uploader(
    "Envie imagens/áudio (png, jpg, mp3, etc)",
    type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4"],
    accept_multiple_files=True,
)

chat_input_value = st.chat_input("Pergunte sobre pastagem...")

col_btn, _ = st.columns([0.4, 0.6])
with col_btn:
    loc_btn_clicked = st.button("📍 Enviar Localização da Propriedade")

loc_message = """Peça ao agente Coletor que guarde as seguintes coordenadas Lat: 13°46'53,13" S Long: 49°08'50,9". Em seguida, peça ao agente Analista que gere uma visualização da minha propriedade rural."""

user_query = None

if loc_btn_clicked:
    user_query = loc_message
elif chat_input_value:
    user_query = chat_input_value

def process_uploaded_files(uploaded_files) -> List[str]:
    """Salva arquivos temporariamente e retorna os caminhos para o Agente."""
    file_paths = []
    if uploaded_files:
        for uploaded_file in uploaded_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                file_paths.append(tmp_file.name)
    return file_paths

if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    image_paths = process_uploaded_files(files_uploaded)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            with st.spinner("Analisando dados e gerando resposta (via API)..."):
                # 1. Conexão com o Redis
                r = redis.Redis(host='redis_cache', port=6379)

                value_bytes = r.get(st.session_state.session_id)

                if not value_bytes:
                    run_response = easter_egg_agent.run(input=user_query, user_id=st.session_state.session_id)

                    print("============= First ===============")
                    print(run_response, flush=True)
                    print('\n\n', flush=True)

                    if run_response.is_paused:
                        dados_bytes = pickle.dumps({'run_response': run_response})
                        r.set(st.session_state.session_id, dados_bytes)

                        for tool in run_response.tools_requiring_confirmation:
                            content = {'comecar_rodeio_tool': "Esta pronto para começar o rodeio?"}[tool.tool_name]

                        for requirement in run_response.active_requirements:
                            if requirement.needs_user_input:
                                input_schema: List[UserInputField] = requirement.user_input_schema

                                for field in input_schema:
                                    content = f"Qual o valor? \nField: {field.name} \nDescription: {field.description} \nType: {field.field_type}"
                    else:
                        content = run_response.content

                elif value_bytes:
                    value = pickle.loads(value_bytes)

                    run_response = value['run_response']

                    for tool in run_response.tools_requiring_confirmation:
                        tool.confirmed = user_query.lower() == "sim"

                    run_response = easter_egg_agent.continue_run(run_response=run_response)

                    print("============= Second ===============")
                    print(run_response, flush=True)
                    print('\n\n', flush=True)

                    content = run_response.content
                        
                    r.delete(st.session_state.session_id)

            full_response = content
            
            message_placeholder.markdown(full_response)

        except Exception as e:
            st.error(f"Erro ao processar: {e}")
        finally:
            pass

    st.session_state.messages.append({"role": "assistant", "content": full_response})