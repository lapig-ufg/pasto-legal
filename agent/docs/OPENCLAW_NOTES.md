# OpenClaw — notas de pesquisa

Pesquisa feita em docs.openclaw.ai + github.com/openclaw/openclaw (via WebSearch/WebFetch,
ago/2026) para adaptar a camada `agent/` do padrão `refac/pi-sdk-develop` (que usa o
runtime `pi`) para o **OpenClaw**. Tudo abaixo é citação/paráfrase da doc oficial; onde a
doc não deixou claro, está marcado como `TODO`.

**Atualização (verificação ao vivo, mesmo dia)**: depois de escrever a pesquisa abaixo,
instalei o CLI real (`npm install -g openclaw@latest`, versão instalada: `2026.7.1-2`) e
testei o config gerado e o plugin contra o binário de verdade — não só contra a doc. Isso
corrigiu **três erros reais** que a doc (ou espelhos de terceiros dela) tinha me levado a
cometer. Detalhes e o que ficou confirmado × ainda incerto estão na seção 7/8 no final —
leia essa seção antes de confiar em qualquer JSON de exemplo daqui de cima.

## 1. O que é o Gateway

> "The Gateway is the local control plane for sessions, tools, events, and channel
> connections."

Um único processo Node sempre ativo (`openclaw gateway`), ouvindo numa porta HTTP+WS
multiplexada (padrão `18789`). CLI, TUI, Control UI e canais (WhatsApp, Telegram, Slack...)
conversam todos com esse processo. Diferente do `pi` (um subprocesso por usuário, protocolo
JSON-RPC via stdin/stdout), o OpenClaw é **um único daemon** — a multiplicação por usuário
acontece em outra camada (sessões), não em processos.

Comando de subida: `openclaw gateway --port 18789 [--verbose]`.
Outros comandos úteis: `openclaw gateway status`, `openclaw onboard --install-daemon`.

## 2. Como enviar mensagem e receber resposta programaticamente

O Gateway expõe um endpoint **compatível com OpenAI Responses API**:

```
POST /v1/responses          (compartilha a porta do Gateway)
```

Desabilitado por padrão — precisa habilitar `gateway.http.endpoints.responses.enabled: true`
no config. Autenticação por `Authorization: Bearer <token>` (shared-secret) na maioria dos
setups.

Request mínimo:
```json
{ "model": "openclaw/<agentId>", "input": "mensagem do usuário" }
```
Response (não-streaming):
```json
{
  "id": "response_...", "status": "completed",
  "output": [
    { "type": "message", "role": "assistant", "content": "..." },
    { "type": "function_call", "id": "call_123", "name": "tool_name", "arguments": "{...}" }
  ],
  "usage": { "input_tokens": 10, "output_tokens": 20 }
}
```
Streaming (`stream: true`) usa SSE (`response.output_text.delta`, ..., `response.completed`).

Headers relevantes: `x-openclaw-agent-id` (seleciona o agente), `x-openclaw-session-key`
(roteamento explícito de sessão), `x-openclaw-model` (override de modelo, exige escopo admin).

**Importante**: o `function_call` no output só aparece para *client-side tools* declaradas
no próprio request (`tools: [{type:"function", ...}]`, estilo OpenAI). Tools registradas via
**plugin** (`api.registerTool`, rodando dentro do Gateway) são executadas server-side e o
resultado já vem embutido na mensagem final — sem round-trip do chamador. É esse o
comportamento que queremos espelhar (equivalente aos eventos `tool_execution_start/end` do
`pi`), então usamos plugin, não client-side tools.

## 3. Sessões e multi-usuário

> "Different personalities are supported through per-agent workspace files... separate auth
> and sessions... true isolation requires one agent per person" — mas isso se refere a
> *personas* (operador), não a milhares de usuários finais de um bot de WhatsApp.

Ponto chave para o nosso caso (muitos usuários finais, um número de WhatsApp): dentro de
**um único agente**, o Gateway já multiplexa sessões por chave:

- Formato da chave: `agent:<agentId>:<mainKey>`.
- Por padrão cada request HTTP é **stateless** (gera sessão nova a cada chamada).
- Se o request incluir o campo `user` (estilo OpenAI `user` string), o Gateway deriva uma
  `mainKey` estável a partir dele — chamadas repetidas com o mesmo `user` reusam a mesma
  sessão/histórico.
- Alternativa: header `x-openclaw-session-key` para controle explícito.

**Decisão**: 1 agente só (`pasto-legal`, nosso único prompt/persona) + `user_id` do WhatsApp
no campo `user` (ou `x-openclaw-session-key: agent:pasto-legal:<user_id>`) a cada chamada.
Isso substitui o "1 processo pi por usuário" do `PiRpcPool` por "1 processo Gateway, N sessões
lógicas via chave" — mais leve, sem gerenciar subprocessos por usuário.

Reset de sessão: não há endpoint HTTP documentado para deletar sessão. A doc documenta
comandos de chat (`"/new"` ou `"/reset"` como mensagem de input reinicia a sessão) e CLI
(`openclaw sessions cleanup`, `openclaw sessions --json`). Usamos o comando de chat `/new`
como `input` para implementar `/reset`.

## 4. Como registrar tools (plugin)

Plugin de tools = pacote JS usando o **plugin SDK**. Forma **confirmada** rodando o
Gateway de verdade (ver seção 8) — duas correções em relação ao que a doc sugeria:

```js
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
// NÃO "typebox" — ver seção 7. parameters é JSON Schema puro.

export default definePluginEntry({
  id: "pasto-legal-tools",
  name: "Pasto Legal Tools",
  register(api) {
    api.registerTool({
      name: "get_pasture_stats",
      description: "...",
      parameters: { type: "object", properties: { ... }, required: [...], additionalProperties: false },
      async execute(_id, params) {
        return { content: [{ type: "text", text: "..." }], details: { ... } };
      },
    }, { optional: true });
  },
});
```

Manifesto: **confirmado** que o arquivo se chama `openclaw.plugin.json` (não `plugin.json`
— `openclaw config validate` recusa o config apontando pra um plugin sem esse arquivo
exato, com o erro `plugin manifest not found: .../openclaw.plugin.json`). Também precisa
de `configSchema` (mesmo vazio) e `activation.onStartup: true`, ou `config validate`
recusa com `plugin manifest requires configSchema`. Exemplo confirmado (baseado nos
manifestos reais empacotados em `node_modules/openclaw/dist/extensions/*/openclaw.plugin.json`):
```json
{
  "id": "pasto-legal-tools",
  "name": "Pasto Legal Tools",
  "activation": { "onStartup": true },
  "enabledByDefault": true,
  "contracts": { "tools": ["get_pasture_stats", "..."] },
  "toolMetadata": { "get_pasture_stats": { "optional": true } },
  "configSchema": { "type": "object", "additionalProperties": false, "properties": {} }
}
```

Carregamento do plugin local (sem publicar no ClawHub) — **confirmado**, o Gateway
carregou nosso plugin sem erro assim que os dois pontos acima foram corrigidos:
- `plugins.load.paths: ["<caminho absoluto para agent/openclaw-plugin>"]` no config.
- `plugins.entries.<id>.enabled: true`.
`TODO` ainda em aberto: hot-reload de plugin local editado — não testei editar o plugin
com o Gateway já rodando; assumo que precisa restart (mais seguro pro protótipo).

## 5. Prompt / persona (equivalente ao AGENTS.md)

Cada agente tem uma pasta `workspace` com `AGENTS.md` (mesmo nome/formato do `pi`!) e
opcionalmente `SOUL.md`/`IDENTITY.md`. Ou seja, **o `agent/AGENTS.md` existente é reusável
sem alterações** — só precisa estar na pasta de workspace apontada pelo config do agente.

Config do agente — **corrigido após testar contra `openclaw config schema`**: agentes são
uma **lista** (`agents.list: [...]`), não um mapa `agents.entries` (isso era uma invenção
de espelho de doc de terceiros, não da doc real — ver seção 7). `tools.profile` também é
um enum fechado (`minimal|coding|messaging|full`), não string livre:
```json5
{
  gateway: { mode: "local", http: { endpoints: { responses: { enabled: true } } } },
  agents: {
    list: [
      {
        id: "pasto-legal",
        default: true,
        name: "Pasto Legal",
        workspace: "<caminho absoluto para agent/openclaw-workspace>",   // contém AGENTS.md
        model: "google/gemini-3.5-flash-lite",
        tools: { profile: "full", alsoAllow: ["get_pasture_stats", "..."] },
      },
    ],
  },
}
```
`gateway.mode: "local"` também é obrigatório — sem ele o `gateway` recusa subir
(`gateway.mode is unset; gateway start will be blocked`, visto via `openclaw doctor`).
Injeção de contexto por mensagem (session-state, tools relevantes do Tool-RAG) — não existe
"system prompt por request" documentado; usamos o campo `instructions` do `/v1/responses`
(mesclado ao prompt do sistema) OU concatenamos ao `input`, do mesmo jeito que
`pi_rpc.build_prompt()` fazia concatenando `<session-state>`/lista de tools ao prompt.

## 6. Tool-RAG (`tool_rag.py` / `registry.py`) — reusar ou não?

OpenClaw tem seleção de tools **estática** por config (`tools.profile`, `tools.allow/deny`) —
não há busca semântica por mensagem equivalente ao Tool-RAG. **Decisão: manter
`tool_rag.py`/`registry.py` como estão** (são agnósticos de runtime, puro Python) e usar
`search_tools()` para montar o bloco `instructions` de cada request, exatamente como
`build_prompt()` fazia para o `pi`. O plugin registra TODAS as tools no Gateway (senão o
Gateway não sabe executá-las), mas o texto de instruções injetado por mensagem continua
dizendo ao modelo "use apenas estas 5" — mesmo mecanismo de "Zero Prompt Bloat" de antes,
só que a restrição é por instrução de prompt, não por lista de tools do protocolo (o pi
também não removia as tools do protocolo, elas ficavam registradas na extensão; a lista
"relevant_tools" só entra como texto no prompt).

## 7. O que a pesquisa (doc/WebFetch) acertou vs. errou — visto ao vivo

A doc oficial (`docs.openclaw.ai`) parece ter mudado ou nunca ter documentado alguns
detalhes de config com precisão, e os resultados de WebFetch (que resumem páginas,
possivelmente misturando espelhos de terceiros como `openclaw-ai.com`, `clawdocs.org`,
`openclawlab.com` — não o site oficial) erraram em dois pontos estruturais que só
apareceram ao rodar o CLI de verdade (`openclaw@2026.7.1-2`, instalado localmente):

| Assumido pela pesquisa (doc) | Realidade (`openclaw config schema` / `config validate`) |
|---|---|
| `agents.entries.<id>` (mapa) + `ownership: "explicit"` | `agents.list` (**array** de `{id, default, ...}**`) — `ownership`/`entries` não existem no schema |
| `tools.profile: "custom"` (string livre) | enum fechado: `minimal\|coding\|messaging\|full` |
| Manifesto de plugin: nome incerto, sugeria `plugin.json` | **`openclaw.plugin.json`**, exige `configSchema` |
| `import { Type } from "typebox"` (como no `pi`) | Não existe esse pacote pro OpenClaw resolver — usa **JSON Schema puro** em `parameters` |
| `gateway.mode` — não mencionado | **obrigatório**, precisa ser `"local"` ou o gateway recusa subir |

O que a pesquisa acertou (confirmado ao vivo):
- `POST /v1/responses` — endpoint, habilitação via `gateway.http.endpoints.responses.enabled`,
  formato de request/response (`output[]`, `usage`, `status`), tudo bateu exatamente com o
  que veio de volta do Gateway real.
- `model: "openclaw/<agentId>"` — `GET /v1/models` retornou literalmente
  `openclaw`, `openclaw/default`, `openclaw/pasto-legal` como documentado.
- `--auth none` funciona via flag de CLI mesmo com a doc recomendando token por padrão.
- `plugins.load.paths` (array de paths locais) — carregou nosso plugin sem erro.

## 8. Verificação ao vivo feita nesta sessão

Rodei o `openclaw` real (não só a doc) contra o config e o plugin gerados por
`agent/openclaw_pool.py` / `agent/openclaw-plugin/`:

1. `openclaw config validate` — **passou** depois das correções da tabela acima.
2. `openclaw gateway --port ... --profile pasto-legal-verify --auth none --verbose` —
   **subiu com sucesso**; log mostrou `pasto-legal-tools` entre os plugins carregados
   (`loaded 10 plugin(s) (10 attempted)`, zero erros).
3. `GET /v1/models` — retornou `openclaw/pasto-legal` como esperado.
4. `POST /v1/responses` com `model: "openclaw/pasto-legal"`, `input`, `user` — request
   aceito, formato de resposta bateu com o parser do `OpenClawSessionClient.prompt()`.
5. Com a `GOOGLE_API_KEY` real do `.env` do projeto: o Gateway roteou corretamente pro
   provider `google`/`gemini-3.5-flash-lite` e fez a chamada HTTP real pra
   `generativelanguage.googleapis.com` — mas a chave em `.env` está **inválida/expirada**
   (`400 API key not valid`, confirmado batendo direto na API do Google, fora do
   OpenClaw). Isso não é um bug da integração — é a chave do `.env` local; com uma chave
   válida o fluxo deveria completar. Achado um bug real nosso nesse processo:
   `OpenClawGatewayManager._wait_ready()` só capturava `httpx.ConnectError`/`ReadTimeout`
   e perdia `httpx.ConnectTimeout` (erro real observado), fazendo o healthcheck falhar
   por engano no primeiro boot de um profile novo (que é mais lento por causa de setup
   automático do OpenClaw). Corrigido para capturar `httpx.HTTPError` genérico.
6. **Não testado ao vivo**: o round trip completo de uma tool call (plugin → `POST /tool`
   → `agent/tools/*.py` → GEE/SICAR) — exigiria a API completa (FastAPI + Valkey + chave
   Google válida) rodando de ponta a ponta, fora do escopo desta verificação isolada do
   runtime do agente. O código do plugin (`callTool()`) é uma porta quase literal do
   `pasto-legal-tools.js` já usado em produção pela variante `pi`, então o risco
   remanescente está concentrado em como o OpenClaw expõe (ou não) `details.sessionState`
   no output de `/v1/responses` — por isso `OpenClawSessionClient` lê o estado direto do
   Valkey em vez de depender disso (ver `_read_session_state`).

Ambiente usado pra verificação: Windows local (não o alvo de deploy real, que é o
container Docker/Linux do `Dockerfile`). Um detalhe puramente local não vazou pro código:
o `node` do sistema (v24.14.1) não satisfaz a exigência do CLI (`>=24.15.0`), então usei
um binário `node` mais novo (baixado via `npx node@24.15.0`) só para os testes manuais —
`agent/openclaw_pool.py` continua chamando `openclaw` puro, que é o caminho certo no
container Linux (Node 22 instalado fresco pelo `Dockerfile`).
