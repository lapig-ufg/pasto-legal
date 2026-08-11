"""Streamlit debug webapp — calls FastAPI /chat endpoint.

Thin UI layer — all LLM processing happens in the FastAPI container.
"""
import os
import uuid
import json
import base64
import tempfile
import streamlit as st
import httpx

from typing import List
from dataclasses import dataclass

from api.configs.config import config
from api.interfaces.streamlit.debug_helpers import extract_pi_debug_data
from api.interfaces.streamlit.debug_panel import render_debug_panel

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:3000")

st.set_page_config(page_title="Pasto Legal", page_icon="P")

DB_FILE = "users_db.json"


# ── Simple media containers (no agno) ────────────────────────────────────

@dataclass
class Image:
    filepath: str

@dataclass
class Audio:
    filepath: str
    ext: str = ""


# ── User DB ──────────────────────────────────────────────────────────────

def get_users():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r") as file:
            return json.load(file)
    except Exception:
        return []

def new_user(user_id, user_name):
    users = get_users()
    if not any(user["id"] == user_id for user in users):
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
    st.session_state.debug_log = []
    st.session_state.debug_session_state = {}
    st.session_state.debug_agent_routing = []
    st.session_state.debug_tool_calls = []
    st.session_state.debug_metrics = []
    st.session_state.debug_messages = []
    st.session_state.chat_session_state = {}
    st.rerun()


# ── Login screen ────────────────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("Login - Pasto Legal")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Historico")
        stored_users = get_users()
        if stored_users:
            selected_obj = st.selectbox(
                "Escolha o usuário:",
                stored_users,
                format_func=lambda x: x.get("nickname", "Usuário"),
            )
            if st.button("Entrar"):
                login_user(selected_obj["id"], selected_obj["nickname"])
        else:
            st.info("Vazio")

    with col2:
        st.subheader("Novo")
        new_name_input = st.text_input("Identificação do usuário")
        if st.button("Criar"):
            if new_name_input.strip():
                new_id = str(uuid.uuid4())
                new_user(new_id, new_name_input)
                login_user(new_id, new_name_input)
            else:
                st.warning("Por favor, digite um nome.")

    with col3:
        st.subheader("Anonimo")
        if st.button("Entrar Anonimamente"):
            anon_id = str(uuid.uuid4())
            login_user(anon_id, "Visitante Anônimo")

    st.stop()


# ── Main chat ───────────────────────────────────────────────────────────

with st.sidebar:
    st.sidebar.title("Configurações")
    st.write(f"**Usuario:** {st.session_state.get('user_name', 'Desconhecido')}")
    st.caption(f"ID: {st.session_state['session_id']}")
    st.divider()
    if st.button("Sair / Trocar Usuário"):
        logout()

    st.divider()
    if st.button("🔄 Reset Session"):
        import httpx, asyncio
        async def _reset():
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{FASTAPI_URL}/reset", json={"user_id": st.session_state.session_id})
        asyncio.run(_reset())
        st.session_state.messages = []
        st.session_state.chat_session_state = {}
        st.rerun()

    if config.DEBUG_MODE:
        st.divider()
        st.session_state.debug_mode_enabled = st.toggle(
            "Debug Mode",
            value=st.session_state.get("debug_mode_enabled", True),
            key="debug_mode_toggle",
        )
        if st.session_state.debug_mode_enabled:
            render_debug_panel()

st.title(f"Ola, {st.session_state.get('user_name', '')}")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Debug state init
for key in ("debug_log", "debug_session_state", "debug_agent_routing",
            "debug_tool_calls", "debug_metrics", "debug_messages"):
    if key not in st.session_state:
        st.session_state[key] = [] if key != "debug_session_state" else {}

if "chat_session_state" not in st.session_state:
    st.session_state.chat_session_state = {}

# Show message history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "images" in message:
            for img in message["images"]:
                # img may be bytes (new) or base64 string (old)
                if isinstance(img, str):
                    import base64 as _b64
                    try:
                        img = _b64.b64decode(img)
                    except Exception:
                        continue
                st.image(img, use_container_width=True)
        if "audio" in message:
            for aud in message["audio"]:
                if os.path.exists(aud):
                    st.audio(aud, format="audio/ogg")

# Input widgets
if "file_uploader_key" not in st.session_state:
    st.session_state.file_uploader_key = 0

files_uploaded = st.file_uploader(
    "Envie imagens/áudio",
    key=f"file_uploader_{st.session_state.file_uploader_key}",
    type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4"],
    accept_multiple_files=True,
)

if "audio_uploader_key" not in st.session_state:
    st.session_state.audio_uploader_key = 0

audio_input_value = st.audio_input(
    "Gravar audio",
    key=f"audio_uploader_{st.session_state.audio_uploader_key}",
)

chat_input_value = st.chat_input("Pergunte sobre pastagem...")

col_btn, _ = st.columns([0.4, 0.6])
with col_btn:
    loc_input_value = st.button("Enviar Localizacao da Propriedade")

user_query = None

if loc_input_value:
    user_query = "Minhas coordenadas são Lat: -15.82994 S Long: -49.43353."
elif chat_input_value:
    user_query = chat_input_value
elif audio_input_value or (files_uploaded and any(
    f.name.lower().endswith((".wav", ".mp3", ".ogg", ".mp4", ".m4a"))
    for f in files_uploaded
)):
    # Audio-only submissions are sent with a placeholder; the backend
    # transcribes and returns the text via ``transcribed_message``.
    user_query = "[Áudio recebido]"


def process_uploaded_files(uploaded_files) -> List[str]:
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

    image_paths = [p for p in all_file_paths if p.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    audio_paths = [p for p in all_file_paths if p.lower().endswith(('.wav', '.mp3', '.ogg', '.mp4', '.m4a'))]

    def _read_b64(path: str) -> tuple[str, str]:
        with open(path, "rb") as f:
            data = f.read()
        ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "wav": "audio/wav", "mp3": "audio/mpeg",
            "ogg": "audio/ogg", "mp4": "audio/mp4", "m4a": "audio/mp4",
        }
        return base64.b64encode(data).decode(), mime_map.get(ext, "application/octet-stream")

    images_payload = [{"data": _read_b64(p)[0], "mime_type": _read_b64(p)[1]} for p in image_paths]
    audio_payload = [{"data": _read_b64(p)[0], "mime_type": _read_b64(p)[1]} for p in audio_paths]

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        response_images = []
        response_audio = []
        decoded_images = []

        try:
            with st.spinner("Analisando dados e gerando resposta..."):
                # ── Call FastAPI /chat endpoint ──
                async def _call_fastapi():
                    async with httpx.AsyncClient(timeout=300) as client:
                        resp = await client.post(
                            f"{FASTAPI_URL}/chat",
                            json={
                                "user_id": st.session_state.session_id,
                                "message": user_query,
                                "session_state": st.session_state.chat_session_state,
                                "images": images_payload,
                                "audio": audio_payload,
                            },
                        )
                        resp.raise_for_status()
                        return resp.json()

                import asyncio
                pi_result = asyncio.run(_call_fastapi())

            full_response = pi_result.get("content", "Erro ao processar.")
            response_images = pi_result.get("images", [])
            response_audio = pi_result.get("audio", [])

            # If the backend transcribed audio, replace the placeholder shown
            # to the user with the actual recognized text.
            transcribed = pi_result.get("transcribed_message")
            if transcribed and user_query == "[Áudio recebido]":
                user_query = transcribed
                st.session_state.messages[-1]["content"] = transcribed
                message_placeholder.markdown("")  # clear placeholder, will rerun

            if "session_state" in pi_result and isinstance(pi_result["session_state"], dict):
                st.session_state.chat_session_state = pi_result["session_state"]

            # Extract debug data
            try:
                debug_data = extract_pi_debug_data(
                    pi_result=pi_result,
                    session_id=st.session_state.session_id,
                    user_query=user_query,
                )
                st.session_state.debug_log.append(debug_data)
                st.session_state.debug_agent_routing.extend(debug_data.get("agent_routing_trace", []))
                st.session_state.debug_tool_calls.extend(debug_data.get("tool_calls_log", []))
                st.session_state.debug_metrics.append(debug_data.get("metrics_summary", {}))
                st.session_state.debug_messages.extend(debug_data.get("message_history", []))
                st.session_state.debug_session_state = debug_data.get("session_state", {})
            except Exception:
                import traceback
                traceback.print_exc()

            # Display images from pi response (base64)
            import base64 as b64
            for img_b64 in response_images:
                try:
                    img_data = b64.b64decode(img_b64)
                    decoded_images.append(img_data)
                    st.image(img_data, use_container_width=True)
                except Exception:
                    pass

            # Display audio from pi response
            for audio_path in response_audio:
                if os.path.exists(audio_path):
                    st.audio(audio_path, format="audio/ogg")

            message_placeholder.markdown(full_response)

        except Exception as e:
            import traceback
            traceback.print_exc()
            st.error(f"Erro ao processar: {e}")
            full_response = f"Desculpe, ocorreu um erro: {str(e)}"
        finally:
            for path in image_paths + audio_paths:
                try:
                    os.remove(path)
                except Exception:
                    pass

    if full_response:
        new_message = {"role": "assistant", "content": full_response}
        if decoded_images:
            new_message["images"] = decoded_images  # raw bytes, not base64
        if response_audio:
            new_message["audio"] = response_audio
        st.session_state.messages.append(new_message)
        st.session_state.file_uploader_key += 1
        st.session_state.audio_uploader_key += 1
        st.rerun()
