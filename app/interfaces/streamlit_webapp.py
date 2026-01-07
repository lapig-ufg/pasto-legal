import streamlit as st
import time
import requests
import random

st.title("🐂 Chat Box Pasto Legal")

# Initialize chat history and session_id in session state if they don't exist
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    # Generate a random session ID for the user's session
    st.session_state.session_id = str(random.randint(10000, 99999))

# Display past messages from session state
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


files_uploaded = st.file_uploader(
        "Envie imagens/áudio (png, jpg, webp, wav, mp3, mp4)",
        type=["png", "jpg", "jpeg", "webp", "wav", "mp3", "mp4", "mpeg"],
        accept_multiple_files=True,
)   

# '''NOT STREAM INTERACTIONS'''
# Get user input from chat input box
if user_query := st.chat_input("Pergunte sobre pastagem..."):

    # Add user message to history and display it
    payload = {
        "message": user_query,
        "session_id": st.session_state.session_id,
    }

    files = []
    for f in files_uploaded or []:
        # requests precisa de (campo, (nome, fileobj, mime))
        files.append(("files", (f.name, f, f.type or "application/octet-stream")))

    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    # Generate and display assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        # --- Call the FastAPI chatbot ---
        api_url = "http://localhost:3000/teams/pasto-legal-team/runs"
        payload = {
            "message": user_query,
            "session_id": st.session_state.session_id,
            "stream": False,
        }
        
        try:
            api_response = requests.post(api_url, data=payload, files=files)
            api_response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
            
            # --- IMPORTANT ---
            # Adjust `.get("content")` based on the actual key in your API's JSON response
            assistant_response = api_response.json().get("content", "Sorry, I received an unexpected response format.")

        except requests.exceptions.RequestException as e:
            assistant_response = f"Error: Could not connect to the chatbot API. Please make sure it's running. Details: {e}"
        
        # Simulate a streaming response for a better user experience
        for chunk in assistant_response.split():
            full_response += chunk + " "
            time.sleep(0.05)
            # Add a blinking cursor to simulate typing
            message_placeholder.markdown(full_response + "▌")
        message_placeholder.markdown(full_response)
    
        
    # Add assistant's response to chat history
    st.session_state.messages.append({"role": "assistant", "content": full_response})



# # Obtém a entrada do usuário na caixa de chat.
# if user_query := st.chat_input("Pergunte-me qualquer coisa..."):
#     # Adiciona a mensagem do usuário ao histórico e a exibe.
#     st.session_state.messages.append({"role": "user", "content": user_query})
#     with st.chat_message("user"):
#         st.markdown(user_query)

#     # Gera e exibe a resposta do assistente.
#     with st.chat_message("assistant"):
#         message_placeholder = st.empty()
#         full_response = ""
        
#         # --- Chama o endpoint de STREAMING do FastAPI ---
#         # A URL agora aponta para a nova rota /runs/stream.
#         api_url = "http://localhost:7778/flora/runs/stream?team_id=multi_language_team"
#         payload = {
#             "message": user_query,
#             "session_id": st.session_state.session_id
#         }
        
#         try:
#             # A requisição é feita com stream=True para manter a conexão aberta.
#             with requests.post(api_url, json=payload, stream=True) as response:
#                 response.raise_for_status()  # Lança um erro para respostas ruins (4xx ou 5xx).
                
#                 # Itera sobre cada linha da resposta do stream.
#                 for line in response.iter_lines():
#                     if line:
#                         # Decodifica a linha (bytes) para string.
#                         decoded_line = line.decode('utf-8')
#                         # Processa apenas as linhas que seguem o padrão SSE "data: ...".
#                         if decoded_line.startswith('data:'):
#                             try:
#                                 # Remove o prefixo "data: " e carrega o JSON.
#                                 data = json.loads(decoded_line[5:])
#                                 chunk = data.get("content", "")
#                                 # Adiciona o pedaço à resposta completa.
#                                 full_response += chunk
#                                 # Atualiza o placeholder na tela em tempo real.
#                                 message_placeholder.markdown(full_response + "▌")
#                             except json.JSONDecodeError:
#                                 # Ignora linhas que não são JSON válido, se houver.
#                                 continue
            
#             # Remove o cursor piscante ao final.
#             message_placeholder.markdown(full_response)

#         except requests.exceptions.RequestException as e:
#             full_response = f"Erro: Não foi possível conectar à API do chatbot. Detalhes: {e}"
#             message_placeholder.markdown(full_response)
        
#     # Adiciona a resposta completa do assistente ao histórico do chat.
#     st.session_state.messages.append({"role": "assistant", "content": full_response})











# ''' WebSocket'''
# async def get_bot_response(user_query, session_id, message_placeholder):
#     uri = "ws://localhost:7778/flora/runs/ws"
#     full_response = ""
    
#     try:
#         # Estabelece a conexão com o servidor.
#         async with websockets.connect(uri) as websocket:
#             # 1. Prepara o payload com a mensagem e o session_id.
#             payload = {
#                 "message": user_query,
#                 "session_id": session_id
#             }

#             # 2. Envia o payload como uma string JSON.
#             await websocket.send(json.dumps(payload))

#             # 3. Ouve as respostas do servidor em um loop.
#             while True:
#                 # Aguarda a chegada de uma nova mensagem do servidor.
#                 response_str = await websocket.recv()
#                 response_data = json.loads(response_str)

#                 # Verifica se o servidor enviou uma mensagem de "fim de stream".
#                 if response_data.get("status") == "done":
#                     break
                
#                 # Se a mensagem contiver um pedaço de texto, processa-o.
#                 if "content" in response_data:
#                     chunk = response_data["content"]
#                     full_response += chunk
#                     # Atualiza o placeholder na tela em tempo real.
#                     message_placeholder.markdown(full_response + "▌")

#         # Remove o cursor piscante ao final da resposta completa.
#         message_placeholder.markdown(full_response)
#         return full_response

#     except Exception as e:
#         error_message = f"Erro na conexão WebSocket: {e}. Verifique se o servidor FastAPI está rodando."
#         st.error(error_message)
#         return error_message


# if user_query := st.chat_input("Pergunte-me qualquer coisa..."):
#     # Adiciona a mensagem do usuário ao histórico e a exibe.
#     st.session_state.messages.append({"role": "user", "content": user_query})
#     with st.chat_message("user"):
#         st.markdown(user_query)

#     # Gera e exibe a resposta do assistente.
#     with st.chat_message("assistant"):
#         message_placeholder = st.empty()
        
#         # Chama a função assíncrona para obter a resposta via WebSocket.
#         # asyncio.run() é a ponte entre o mundo síncrono do Streamlit e o
#         # mundo assíncrono da nossa função.
#         assistant_response = asyncio.run(
#             get_bot_response(user_query, st.session_state.session_id, message_placeholder)
#         )
        
#         # Adiciona a resposta final ao histórico do chat.
#         st.session_state.messages.append({"role": "assistant", "content": assistant_response})