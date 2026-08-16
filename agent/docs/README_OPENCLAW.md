# Pasto Legal — variante single-agente (OpenClaw)

Protótipo comparativo: mesmo backend de domínio (`api/`), trocando só o runtime do
agente. Esta branch (`refac/openclaw-develop`) usa o **OpenClaw**; a branch irmã
`refac/pi-sdk-develop` usa o `pi`. Pesquisa e decisões de design em
[`OPENCLAW_NOTES.md`](./OPENCLAW_NOTES.md).

## Arquitetura

```
WhatsApp → FastAPI (api/main.py, inalterado) → OpenClawPool.get_client(user_id)
  → OpenClawSessionClient.prompt(msg)   POST /v1/responses, user=user_id
  → Gateway OpenClaw (1 processo só, agente único "pasto-legal")
      workspace: agent/openclaw-workspace/AGENTS.md (o único prompt do sistema)
      plugin:    agent/openclaw-plugin/ (tools registradas)
  → tool chamada pelo modelo → plugin.execute() → POST http://localhost:3000/tool
  → FastAPI /tool (inalterado) → agent/tools/*.py (inalterado) → GEE/SICAR/TTS/DB
```

A fronteira `POST /tool` é a mesma da branch de referência: o agente nunca executa
lógica de domínio, só chama essa rota. Trocar de runtime (pi → OpenClaw → outro)
não exige tocar em `api/services`, `api/guardrails`, `api/database` ou
`agent/tools/*.py`.

Diferença estrutural em relação ao `pi`: o `pi` sobe **um subprocesso por usuário**
(`PiRpcPool`). O OpenClaw sobe **um único processo Gateway** para todos os usuários;
o isolamento por usuário é feito por *session key* (campo `user` em cada request),
não por processo. `agent/openclaw_pool.py` expõe a mesma interface pública que
`agent/pi_rpc.py` (`start/stop/get_client/delete_session`) para que `api/main.py`
mude o mínimo possível — mas por baixo há só 1 processo Node, não N.

Estado de sessão (`session_state`) é lido diretamente do Valkey depois de cada
turno, em vez de vir embutido na resposta do `/v1/responses` — motivo detalhado em
`OPENCLAW_NOTES.md` (a API do OpenClaw é compatível com OpenAI Responses, sem um
canal documentado pra metadado arbitrário de tool, diferente do protocolo RPC
próprio do `pi`).

## Arquivos desta camada

| Arquivo | Papel |
|---|---|
| `agent/openclaw_pool.py` | Gerenciador do processo Gateway + cliente HTTP por usuário + `build_prompt`/`build_onboarding_prompt` |
| `agent/openclaw-plugin/` | Plugin de tools do OpenClaw (`index.js`, `openclaw.plugin.json`, `package.json`) — porta do `pasto-legal-tools.js` da branch `refac/pi-sdk-develop` |
| `agent/openclaw-workspace/AGENTS.md` | Cópia do prompt único do assistente (mesmo arquivo usado pelo `pi`) |
| `agent/registry.py`, `agent/tool_rag.py` | Reusados sem alteração — Tool-RAG (FAISS) continua selecionando as top-5 tools por mensagem |
| `agent/docs/OPENCLAW_NOTES.md` | Pesquisa da doc oficial + gaps conhecidos |

## Como rodar

Pré-requisitos: Node 22+ com `openclaw` instalado globalmente (`npm install -g
openclaw@latest`), Python 3.12 + `uv`, Valkey/Redis rodando.

```bash
# 1. Subir dependências
docker compose up valkey -d   # ou um redis local em VALKEY_HOST/VALKEY_PORT

# 2. Variáveis de ambiente mínimas (ver .env.example)
export GOOGLE_API_KEY=...
export OPENCLAW_MODEL=google/gemini-3.5-flash-lite   # opcional, é o default

# 3. Subir a API — o lifespan do FastAPI sobe o Gateway OpenClaw como subprocesso
uv run uvicorn api.main:app --port 3000 --reload
```

Ou via Docker: `docker compose up` (o `Dockerfile` já instala Node 22 + `openclaw`).

## Caminho de teste manual

1. Suba a API (acima). No log, confirme `[openclaw-gateway] ready pid=... base_url=http://127.0.0.1:18789`.
2. Envie uma mensagem de teste pro `/chat` (mesma rota que o Streamlit debug usa):

   ```bash
   curl -X POST http://localhost:3000/chat \
     -H "Content-Type: application/json" \
     -d '{"user_id": "teste-manual", "message": "como está minha pastagem da fazenda GO-1234567-...?", "session_state": {"terms_accepted": true}}'
   ```

3. Confirme na sequência de log:
   - `[chat] user=teste-manual session_state=...` — mensagem chegou no `/chat`.
   - `[tool-rag] query=... found=... tools=[...]` — Tool-RAG selecionou as tools relevantes.
   - `[tools] → POST http://localhost:3000/tool tool=gee args=...` (log do plugin, no stderr do processo Gateway) — o plugin chamou uma tool.
   - `[tool] → gee args=...` / `[tool] ← gee ok keys=...` (log do FastAPI) — a tool bateu no `/tool` do Python.
   - Resposta HTTP do `/chat` com `content` preenchido — a resposta voltou formatada.
4. Alternativamente, use a interface Streamlit de debug (`api/interfaces/streamlit/streamlit_webapp.py`), que já fala com `/chat`.

Se algo não fechar (ex: `/v1/responses` retornando 404 porque o endpoint não foi
habilitado, ou o plugin não sendo reconhecido), o erro fica documentado nos "Gaps"
de `OPENCLAW_NOTES.md` — não há contorno silencioso escondido no código.

**Já verificado ao vivo** (seção 8 do `OPENCLAW_NOTES.md`): config, plugin e o boot do
Gateway foram testados contra o CLI real (não só a doc) — subiram sem erro, e o
`GOOGLE_API_KEY` do `.env` do projeto chegou a disparar uma chamada real pro Gemini via
OpenClaw (roteamento certo), mas a chave em si voltou `400 API key not valid` direto da
API do Google (confirmado fora do OpenClaw também) — **troque a chave em `.env` antes de
rodar o teste manual**, ou o passo 2 acima vai falhar por causa disso, não por um bug da
integração.
