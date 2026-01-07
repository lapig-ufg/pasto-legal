import os
import uuid
import tempfile
import streamlit as st

from typing import List

from app.agents.main_agent import pasto_legal_team 

st.set_page_config(page_title="Pasto Legal", page_icon="🐂")
st.title("🐂 Chat Box Pasto Legal")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = [] # Zera o visual do chat
    print(f"🆕 Nova Sessão Iniciada: {st.session_state.session_id}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

files_uploaded = st.file_uploader(
    "Envie imagens/áudio (png, jpg, mp3, etc)",
    type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4"],
    accept_multiple_files=True,
)


def process_uploaded_files(uploaded_files) -> List[str]:
    """Salva arquivos temporariamente e retorna os caminhos para o Agente."""
    file_paths = []
    if uploaded_files:
        for uploaded_file in uploaded_files:
            # Cria um arquivo temporário para passar o caminho ao Agente
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                file_paths.append(tmp_file.name)
    return file_paths

if user_query := st.chat_input("Pergunte sobre pastagem..."):
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    image_paths = process_uploaded_files(files_uploaded)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            run_kwargs = {
                "input": user_query,
                "user_id": st.session_state.session_id,
                "stream": True,
            }

            if image_paths:
                run_kwargs["images"] = image_paths 

            response_stream = pasto_legal_team.run(**run_kwargs)
            
            for chunk in response_stream:
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_response += content
                    message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)

        except Exception as e:
            st.error(f"Erro ao processar: {e}")
        finally:
            for path in image_paths:
                try:
                    os.remove(path)
                except:
                    pass

    st.session_state.messages.append({"role": "assistant", "content": full_response})