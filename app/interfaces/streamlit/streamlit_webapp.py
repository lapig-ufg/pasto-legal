import os
import re
import uuid
import json
import random
import tempfile
import streamlit as st

from typing import List
from agno.media import Image, Audio

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
        users.append({"id": user_id, "nickname": user_name})
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
    st.sidebar.title("Configurações")
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
        if "images" in message:
            for img in message["images"]:
                st.image(img, use_container_width=True)
        if "audio" in message:
            for aud in message["audio"]:
                st.audio(aud)

# Inputs do usuário
if 'file_uploader_key' not in st.session_state:
    st.session_state.file_uploader_key = 0

files_uploaded = st.file_uploader(
    "Envie imagens/áudio (png, jpg, mp3, etc)",
    key=f"file_uploader_{st.session_state.file_uploader_key}",
    type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4"],
    accept_multiple_files=True,
)

if "audio_uploader_key" not in st.session_state:
    st.session_state.audio_uploader_key = 0

audio_input_value = st.audio_input(
    "🎤 Gravar áudio",
    key=f"audio_uploader_{st.session_state.audio_uploader_key}",
    )

chat_input_value = st.chat_input("Pergunte sobre pastagem...")

col_btn, _ = st.columns([0.4, 0.6])
with col_btn:
    loc_input_value = st.button("📍 Enviar Localização da Propriedade")

user_query = None

if loc_input_value:
    user_query = """Minhas coordenadas são Lat: -15.82994 S Long: -49.43353."""
elif chat_input_value:
    user_query = chat_input_value
elif audio_input_value:
    user_query = "[Áudio recebido]"

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
        if audio_input_value:
            st.audio(audio_input_value)

    files_to_process = []
    
    if files_uploaded:
        files_to_process.extend(files_uploaded)
    if audio_input_value:
        files_to_process.append(audio_input_value)

    all_file_paths = process_uploaded_files(files_to_process)
    
    image_path = [Image(filepath=p) for p in all_file_paths if p.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    audio_path = [Audio(filepath=p, ext=p[:-4]) for p in all_file_paths if p.lower().endswith(('.wav', '.mp3', '.ogg', '.mp4'))]

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        full_response = ""
        response = None
        
        try:
            run_kwargs = {
                "input": user_query,
                "user_id": st.session_state.session_id,
                "session_id": st.session_state.session_id,
                "stream": False,
            }

            if image_path:
                run_kwargs["images"] = image_path 
            if audio_path:
                run_kwargs["audio"] = audio_path

            # TODO: Implementar files.
            with st.spinner("Analisando dados e gerando resposta..."):
                response = pasto_legal_team.run(**run_kwargs)
            
            if hasattr(response, 'content'):
                full_response = response.content
            else:
                full_response = str(response)

            if response and response.images:
                for img in response.images:
                    st.image(img.content, use_container_width=True)

            audio_to_display = []
            if response and hasattr(response, 'audio') and response.audio:
                audio_to_display.extend(response.audio)
            
            # Tenta extrair áudio de tools_output se a lista principal estiver vazia
            if not audio_to_display and hasattr(response, 'tools_output'):
                for tool_out in response.tools_output:
                    # Verifica se é dicionário
                    if isinstance(tool_out, dict) and 'audio' in tool_out:
                        audio_to_display.extend(tool_out['audio'])
                    # Verifica se é objeto (ToolResult/ToolOutput)
                    elif hasattr(tool_out, 'audio') and tool_out.audio:
                        audio_to_display.extend(tool_out.audio)

            # REGEX: Extração de caminhos de áudio do texto (incluindo padrões tipo path=... ou filepath=...)
            # Procura por caminhos Windows ou caminhos relativos/unix que terminam em extensões de áudio
            audio_patterns = [
                r'(?:path|filepath)\s*=\s*[\'"]?([a-zA-Z]:\\[^\s\(\)\[\]\'",]+?\.(?:ogg|mp3|wav))[\'"]?',
                r'([a-zA-Z]:\\[^\s\(\)\[\]\'",]+?\.(?:ogg|mp3|wav))'
            ]
            
            # DEBUG: Visualizar o que está acontecendo
            with st.expander("Debug: Regex de Áudio"):
                st.write("Regex Patterns:", audio_patterns)
                st.code(full_response, language='text')

            for pattern in audio_patterns:
                matches = re.findall(pattern, full_response, re.IGNORECASE)
                if matches:
                    with st.expander(f"Debug: Matches encontrados ({pattern})"):
                        st.write(matches)

                for path in matches:
                    # Limpa possíveis aspas residuais ou espaços
                    clean_path = path.strip().strip("'").strip('"')
                    
                    if os.path.exists(clean_path):
                         # Evita duplicatas
                         current_paths = [getattr(a, 'filepath', getattr(a, 'path', '')) for a in audio_to_display]
                         # Handle dicts in current_paths (audio_to_display can have dicts now)
                         current_path_strings = []
                         for cp in audio_to_display:
                             if isinstance(cp, dict):
                                 current_path_strings.append(cp.get('filepath') or cp.get('path'))
                             else:
                                 current_path_strings.append(getattr(cp, 'filepath', getattr(cp, 'path', '')))

                         if clean_path not in current_path_strings:
                            audio_to_display.append({'filepath': clean_path})
                    else:
                         with st.expander("Debug: Arquivo não encontrado"):
                             st.write(f"Path extraído mas não existe: {clean_path}")

            if audio_to_display:
                for audio_item in audio_to_display:
                    if isinstance(audio_item, dict):
                        path = audio_item.get('filepath') or audio_item.get('path')
                        content = audio_item.get('content')
                        if path: st.audio(path)
                        elif content: st.audio(content)
                    else:
                        if hasattr(audio_item, 'filepath') and audio_item.filepath:
                            st.audio(audio_item.filepath)
                        elif hasattr(audio_item, 'path') and audio_item.path:
                            st.audio(audio_item.path)
                        elif hasattr(audio_item, 'content') and audio_item.content:
                            st.audio(audio_item.content)
            
            # Debug: Mostra atributos da resposta se não houver áudio
            if not response.audio:
                with st.expander("Debug: Resposta do Agente"):
                    st.write("Atributos:", dir(response))
                    if hasattr(response, 'tools_output'):
                        st.write("Tools Output:", response.tools_output)
            
            # Exibe a resposta final
            message_placeholder.markdown(full_response)

        except Exception as e:
            import traceback
            traceback.print_exc()
            st.error(f"Erro ao processar: {e}")
            full_response = f"Desculpe, ocorreu um erro: {str(e)}"
        finally:
            for path in image_path:
                try:
                    os.remove(path)
                except:
                    pass

    if full_response:
        new_message = {"role": "assistant", "content": full_response}
        if response:
            if response.images:
                new_message["images"] = [img.content for img in response.images]
            if audio_to_display:
                new_message["audio"] = []
                for aud in audio_to_display:
                    if isinstance(aud, dict):
                        path = aud.get('filepath') or aud.get('path')
                        content = aud.get('content')
                        if path: new_message["audio"].append(path)
                        elif content: new_message["audio"].append(content)
                    else:
                        if hasattr(aud, 'filepath') and aud.filepath:
                            new_message["audio"].append(aud.filepath)
                        elif hasattr(aud, 'path') and aud.path:
                            new_message["audio"].append(aud.path)
                        elif hasattr(aud, 'content') and aud.content:
                            new_message["audio"].append(aud.content)
        
        st.session_state.messages.append(new_message)

        st.session_state.file_uploader_key += 1
        st.session_state.audio_uploader_key += 1

        st.rerun()

        