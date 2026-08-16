"""
HTTP client for the OpenClaw Gateway (POST /v1/responses).

Unlike pi (agent/pi_rpc.py), which spawns one subprocess per user and talks
JSON-RPC over stdin/stdout, OpenClaw runs as a single long-lived Gateway
daemon shared by every user. Per-user isolation comes from a session key
derived from the `user` field on each request, not a separate OS process.
See agent/docs/OPENCLAW_NOTES.md (sections 1-3) for the research behind this.

Public surface (start/stop/get_client/delete_session) mirrors PiRpcPool on
purpose, so api/main.py only needs to swap the import.
"""
import json
import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import redis

log = logging.getLogger("pasto-legal.openclaw_pool")
metrics_log = logging.getLogger("pasto-legal.run_metrics")

AGENT_ID = "pasto-legal"
PROFILE = os.getenv("OPENCLAW_PROFILE", "pasto-legal")
DEFAULT_PORT = int(os.getenv("OPENCLAW_GATEWAY_PORT", "18789"))
DEFAULT_HOST = os.getenv("OPENCLAW_GATEWAY_HOST", "127.0.0.1")
DEFAULT_MODEL = os.getenv("OPENCLAW_MODEL", "google/gemini-3.5-flash-lite")

AGENT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = AGENT_DIR / "openclaw-workspace"   # contains AGENTS.md
PLUGIN_DIR = AGENT_DIR / "openclaw-plugin"         # tool plugin (registerTool -> /tool)

PROFILE_HOME = Path.home() / f".openclaw-{PROFILE}"

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))
_valkey = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, db=VALKEY_DB, decode_responses=True)


def _read_session_state(user_id: str) -> dict:
    """Read session state directly from Valkey.

    agent/tools/*.py (e.g. property.py) already persist session state to
    Valkey as a side effect of tool execution — that was true for pi too.
    pi additionally *echoed* state updates back through its custom RPC event
    stream (tool_execution_end.details.sessionState) so pi_rpc.py could merge
    them without a second round trip. OpenClaw's /v1/responses is
    OpenAI-Responses-shaped and has no documented hook for that kind of
    side-channel tool metadata (see OPENCLAW_NOTES.md gap list), so instead
    of threading it through the response we just re-read the same Valkey key
    the tool already wrote to, once the agent run settles.
    """
    raw = _valkey.get(f"session:{user_id}")
    return json.loads(raw) if raw else {}


def _write_gateway_config(model: str) -> Path:
    """Write the OpenClaw profile config for the single pasto-legal agent.

    One agent ("pasto-legal") backed by openclaw-workspace/AGENTS.md, the
    /v1/responses endpoint enabled (disabled by default upstream), and our
    local tool plugin loaded from disk (agent/openclaw-plugin/).

    Shape verified against `openclaw config schema` (installed CLI, ago/2026):
    agents are a `list` (array of {id, ...}), NOT a keyed `entries` map, and
    tools.profile is a closed enum (minimal|coding|messaging|full) — an
    earlier draft of this file had both wrong, based on third-party doc
    mirrors rather than the real schema. See OPENCLAW_NOTES.md section 7.
    """
    plugin_tool_names = _plugin_tool_names()
    config = {
        "gateway": {
            "mode": "local",
            "http": {"endpoints": {"responses": {"enabled": True}}},
        },
        "agents": {
            "list": [
                {
                    "id": AGENT_ID,
                    "default": True,
                    "name": "Pasto Legal",
                    "workspace": str(WORKSPACE_DIR),
                    "model": model,
                    "tools": {"profile": "full", "alsoAllow": plugin_tool_names},
                }
            ],
        },
        "plugins": {
            "load": {"paths": [str(PLUGIN_DIR)]},
            "entries": {"pasto-legal-tools": {"enabled": True}},
        },
    }
    PROFILE_HOME.mkdir(parents=True, exist_ok=True)
    config_path = PROFILE_HOME / "openclaw.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path


def _plugin_tool_names() -> list[str]:
    """Tool names actually registered by agent/openclaw-plugin/index.js.

    Read from openclaw.plugin.json's contracts.tools rather than agent/registry.py's
    TOOLS list — registry.py also contains Tool-RAG/skill-only virtual
    entries (e.g. "ua_calculator", which piggybacks on get_pasture_stats and
    has no registerTool of its own), so it is not a 1:1 map of what the
    plugin exposes.
    """
    manifest = json.loads((PLUGIN_DIR / "openclaw.plugin.json").read_text(encoding="utf-8"))
    return manifest["contracts"]["tools"]


# ── Gateway process manager (ONE process for all users) ────────────────────

class OpenClawGatewayManager:
    """Spawns and supervises the single `openclaw gateway` daemon process."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL):
        self.port = port
        self.host = host
        self.model = model
        self.base_url = f"http://{host}:{port}"
        self.proc: Optional[asyncio.subprocess.Process] = None

    async def start(self, timeout: float = 60.0) -> None:
        if self.proc and self.proc.returncode is None:
            return

        config_path = _write_gateway_config(self.model)
        log.info(f"[openclaw-gateway] config written to {config_path}")

        env = os.environ.copy()
        if "TOOL_BACKEND_URL" not in env:
            env["TOOL_BACKEND_URL"] = "http://localhost:3000"

        # --auth none + --bind loopback: inside a container OpenClaw defaults to
        # bind=auto (0.0.0.0) and REFUSES to bind without auth (exit code 78).
        # We force --bind loopback so auth=none is accepted: the Gateway is a
        # subprocess of this FastAPI process and the sole caller reaches it on
        # 127.0.0.1:<port> — never exposed off-host.
        cmd = ["openclaw", "gateway", "--port", str(self.port), "--profile", PROFILE, "--auth", "none", "--bind", "loopback"]
        if os.getenv("OPENCLAW_VERBOSE", "1") == "1":
            cmd.append("--verbose")

        log.info(f"[openclaw-gateway] spawning: {' '.join(cmd)}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        asyncio.create_task(self._drain(self.proc.stdout, "stdout"))
        asyncio.create_task(self._drain(self.proc.stderr, "stderr"))

        await self._wait_ready(timeout)
        log.info(f"[openclaw-gateway] ready  pid={self.proc.pid}  base_url={self.base_url}")

    async def _drain(self, stream, label: str) -> None:
        while stream:
            line = await stream.readline()
            if not line:
                break
            log.debug(f"[openclaw-gateway:{label}] {line.decode(errors='replace').strip()}")

    async def _wait_ready(self, timeout: float) -> None:
        """Poll GET /v1/models until the Gateway answers (or the process dies)."""
        deadline = time.time() + timeout
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                if self.proc.returncode is not None:
                    raise RuntimeError(
                        f"openclaw gateway exited early with code {self.proc.returncode} — "
                        f"check logs (OPENCLAW_VERBOSE=1 is on by default)"
                    )
                try:
                    resp = await client.get(f"{self.base_url}/v1/models", timeout=2.0)
                    if resp.status_code < 500:
                        return
                except httpx.HTTPError:
                    # Any transient connect/read/timeout error while the Gateway is
                    # still starting up — keep polling until the deadline. An
                    # earlier version only caught ConnectError/ReadTimeout and
                    # missed ConnectTimeout, which happens routinely before the
                    # port is bound (confirmed via live testing, see
                    # OPENCLAW_NOTES.md section 7).
                    pass
                await asyncio.sleep(1.0)
        raise TimeoutError(f"openclaw gateway did not become ready within {timeout}s")

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            log.info("[openclaw-gateway] stopped")
        self.proc = None


# ── Per-user session wrapper (NOT a process — just a routing key) ──────────

class OpenClawSessionClient:
    """Thin per-user wrapper over the shared Gateway's /v1/responses endpoint.

    There is no subprocess here (contrast with PiRpcClient): every user
    shares the one Gateway process from OpenClawGatewayManager. Isolation
    comes from passing `user_id` as the OpenAI-style `user` field, which
    OpenClaw uses to derive a stable per-user session key
    (agent:<agentId>:<mainKey>) — see OPENCLAW_NOTES.md section 3.
    """

    def __init__(self, user_id: str, base_url: str, model: str = f"openclaw/{AGENT_ID}"):
        self.user_id = user_id
        self.base_url = base_url
        self.model = model
        self.last_used = time.time()

    async def prompt(self, message: str, images: list = None) -> dict:
        self.last_used = time.time()
        _t0 = time.time()

        if images:
            payload_input = [{"type": "message", "role": "user", "content": message}]
            for img in images:
                # NOTE: the doc only shows input_image with a "url" source (not raw
                # base64) — we assume a data: URI is accepted. Unverified, see
                # OPENCLAW_NOTES.md gap list; adjust here if the Gateway rejects it.
                data_url = f"data:{img.get('mimeType', 'image/png')};base64,{img['data']}"
                payload_input.append({"type": "input_image", "source": {"type": "url", "url": data_url}})
        else:
            payload_input = message

        body = {"model": self.model, "input": payload_input, "user": self.user_id, "stream": False}

        result = {"content": "", "images": [], "audio": [], "session_state_updates": []}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self.base_url}/v1/responses", json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            log.error(f"[openclaw:{self.user_id[:12]}] request failed: {e}")
            result["content"] = "Desculpa, houve um erro ao processar sua solicitação. Tente novamente."
            self._log_run_metrics(result, _t0)
            return result

        for item in data.get("output", []):
            t = item.get("type")
            if t == "message" and item.get("role") == "assistant":
                content = item.get("content")
                if isinstance(content, str):
                    result["content"] += content
                elif isinstance(content, list):
                    for part in content:
                        ptype = part.get("type")
                        if ptype in ("text", "output_text"):
                            result["content"] += part.get("text", "")
                        elif ptype in ("image", "output_image"):
                            # Best-effort: exact output shape for plugin-tool images is
                            # not confirmed in the doc — see OPENCLAW_NOTES.md gap list.
                            img_data = part.get("data") or (part.get("source") or {}).get("data")
                            if img_data:
                                result["images"].append(img_data)
            elif t == "function_call":
                log.warning(
                    f"[openclaw:{self.user_id[:12]}] unexpected client-side function_call "
                    f"{item.get('name')} — tools are registered server-side via the plugin, "
                    f"this should not normally happen"
                )

        if not result["content"].strip():
            log.error(f"[openclaw:{self.user_id[:12]}] empty reply  status={data.get('status')}")
            result["content"] = "Desculpa, houve um erro ao processar sua solicitação. Tente novamente."

        result["session_state_updates"].append(_read_session_state(self.user_id))
        self._log_run_metrics(result, _t0, data.get("usage"), data.get("status"))
        return result

    def _log_run_metrics(self, result: dict, t0: float, usage: dict = None, status: str = None) -> None:
        elapsed = time.time() - t0
        metrics = {
            "user_id": self.user_id,
            "model": self.model,
            "elapsed_s": round(elapsed, 3),
            "input_tokens": (usage or {}).get("input_tokens", 0),
            "output_tokens": (usage or {}).get("output_tokens", 0),
            "status": status,
            "content_len": len(result.get("content", "")),
            "n_images": len(result.get("images", [])),
        }
        result["metrics"] = metrics
        metrics_log.debug("run_metrics " + json.dumps(metrics, ensure_ascii=False))


# ── Pool (drop-in replacement for PiRpcPool's public surface) ──────────────

class OpenClawPool:
    """Same public surface as PiRpcPool (start/stop/get_client/delete_session).

    Internally there is exactly one Gateway process for every user — not one
    per user — so get_client() just returns a lightweight routing wrapper
    instead of spawning anything.
    """

    def __init__(self, ttl: int = 1800, port: int = DEFAULT_PORT, model: str = DEFAULT_MODEL):
        self._gateway = OpenClawGatewayManager(port=port, model=model)
        self._clients: dict[str, OpenClawSessionClient] = {}
        self._ttl = ttl
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await self._gateway.start()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        await self._gateway.stop()

    async def get_client(self, user_id: str) -> OpenClawSessionClient:
        client = self._clients.get(user_id)
        if not client:
            client = OpenClawSessionClient(user_id, self._gateway.base_url)
            self._clients[user_id] = client
        client.last_used = time.time()
        return client

    async def delete_session(self, user_id: str) -> None:
        """Reset a user's OpenClaw session via the documented "/new" chat command.

        There is no documented HTTP endpoint to delete a session outright —
        see OPENCLAW_NOTES.md section 3.
        """
        client = self._clients.pop(user_id, None) or OpenClawSessionClient(user_id, self._gateway.base_url)
        try:
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                await http_client.post(
                    f"{self._gateway.base_url}/v1/responses",
                    json={"model": client.model, "input": "/new", "user": user_id, "stream": False},
                )
            log.info(f"[pool] reset session  user={user_id[:12]}")
        except Exception as e:
            log.error(f"[pool] reset session failed  user={user_id[:12]}: {e}")
        _valkey.delete(f"session:{user_id}")

    async def _cleanup_loop(self) -> None:
        """Drop idle routing wrappers (there's no process to kill, just a dict)."""
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for user_id in list(self._clients):
                client = self._clients.get(user_id)
                if client and now - client.last_used > self._ttl:
                    del self._clients[user_id]


# ── Prompt builder (ported from agent/pi_rpc.py — runtime-agnostic) ────────

def build_prompt(
    user_message: str,
    user_id: str = "",
    session_state: dict = None,
    relevant_tools: list[str] | None = None,
    audio_input: bool = False,
) -> str:
    """Build the prompt sent as `input` to /v1/responses.

    - System prompt: handled by AGENTS.md (OpenClaw reads it from the agent's
      workspace dir — see openclaw-workspace/AGENTS.md).
    - Session state: injected every message (changes after tool calls).
    - user_id: injected so the LLM can pass it to tools.
    - relevant_tools: Tool-RAG selected tools (see agent/tool_rag.py) — OpenClaw's
      own tool selection is a static per-agent allow/deny profile, not a
      per-message semantic search, so this remains useful. See
      OPENCLAW_NOTES.md section 6.
    - audio_input: when True, the user sent an audio message — instruct the
      LLM to also call `generate_speech` so the reply comes back as audio.
    - History: NOT injected — OpenClaw manages it in the session (keyed by
      the `user` field on the request, see OpenClawSessionClient).
    """
    parts = []

    if audio_input:
        parts.append(
            "## Resposta em áudio\n"
            "O usuário enviou esta mensagem como áudio. Responda normalmente em "
            "texto e DEPOIS chame a ferramenta `generate_speech` com o texto da "
            "sua resposta e o `user_id` da sessão, para que o usuário também "
            "receba a resposta em áudio falado.\n"
        )

    if relevant_tools:
        from agent.registry import TOOLS as _REGISTRY
        name_to_tool = {t["name"]: t for t in _REGISTRY}

        lines = []
        for name in relevant_tools:
            t = name_to_tool.get(name)
            if t:
                lines.append(f"- `{name}`: {t['description']}")
        parts.append(
            "## Ferramentas disponíveis para esta consulta\n"
            "Use APENAS as ferramentas listadas abaixo para responder ao usuário.\n"
            "Não invente ferramentas que não estão nesta lista.\n\n"
            + "\n".join(lines) + "\n"
        )

        skill_lines = []
        for name in relevant_tools:
            t = name_to_tool.get(name)
            if t and t.get("skill"):
                skill_lines.append(f"## Skill: {name}\n{t['skill']}")
        if skill_lines:
            parts.append(
                "## Instruções específicas (skills)\n"
                + "\n\n".join(skill_lines) + "\n"
            )

    parts.append("\n<session-state>")
    parts.append(f"<user-id>{user_id}</user-id>")

    if session_state:
        if session_state.get("user_persona"):
            parts.append(
                f"<user-persona>{json.dumps(session_state['user_persona'], ensure_ascii=False)}</user-persona>"
            )
        if session_state.get("all_properties"):
            parts.append("<registered-properties>")
            for p in session_state["all_properties"]:
                parts.append(f"- CAR: {p.get('car_code', '?')}, Nome: {p.get('nickname', 'sem nome')}")
            parts.append("</registered-properties>")
        if session_state.get("registration_state"):
            parts.append(f"<registration-state>{session_state['registration_state']}</registration-state>")
        if session_state.get("candidate_properties"):
            parts.append("<candidate-properties>")
            for p in session_state["candidate_properties"]:
                parts.append(
                    f"- CAR: {p.get('car_code', '?')}, "
                    f"Área: {p.get('spatial_features', {}).get('total_area', '?')} ha, "
                    f"Município: {p.get('spatial_features', {}).get('municipality', '?')}"
                )
            parts.append("</candidate-properties>")
        if "terms_accepted" in session_state:
            parts.append(f"<terms-accepted>{json.dumps(session_state['terms_accepted'])}</terms-accepted>")
        if session_state.get("feedback_mode"):
            parts.append(f"<feedback-mode>{session_state['feedback_mode']}</feedback-mode>")

    parts.append("</session-state>")
    parts.append(f"\n<user-message>{user_message}</user-message>")
    return "\n".join(parts)


# ── Onboarding prompt (first-time terms acceptance) ─────────────────────────

_ONBOARDING_INSTRUCTIONS = """
INSTRUÇÃO DE SISTEMA IMPERATIVA — Modo Onboarding (Primeiro Acesso)

Você é o Agente de Boas-Vindas do Pasto Legal. O usuário está acessando o sistema pela PRIMEIRA VEZ e ainda NÃO aceitou os Termos de Uso. Seu objetivo absoluto e exclusivo é garantir que o usuário entenda como o sistema funciona e dê seu aceite formal aos Termos de Uso antes de acessar qualquer funcionalidade.

REQUISITO CRÍTICO: Comunique-se SEMPRE em português brasileiro, com linguagem simples e amigável ao trabalhador do campo. Use formatação do WhatsApp (*negrito* com asteriscos, sem markdown). NUNCA diga que é um robô, IA, chatbot ou modelo de linguagem. NUNCA cite termos técnicos de software.

COMO AGIR:
1. **Boas-Vindas e Envio do Link**: Apresente-se de maneira amigável. Explique brevemente que o Pasto Legal usa IA e dados de satélite para monitorar pastagens via WhatsApp. Na sua PRIMEIRA MENSAGEM, você DEVE fornecer a URL dos Termos de Uso: https://pasto.legal/termos-de-uso
2. **NÃO Envie o Texto Completo**: Nunca copie e cole o texto completo dos termos no chat, a menos que seja explicitamente solicitado pelo usuário.
3. **Chamada para Ação**: Nessa mesma primeira mensagem, pergunte diretamente se ele concorda com os termos (ex: "Você está de acordo com os termos do link acima para podermos começar? Basta responder 'Aceito'.").
4. **Esclarecimento de Dúvidas**: Se o usuário fizer perguntas ou tiver dúvidas sobre os termos e condições, use a seção "TERMOS DE REFERÊNCIA" abaixo para explicar e sanar as dúvidas de forma simples e prestativa.
5. **Registro**: Quando o usuário aceitar claramente (ex: "aceito", "sim", "concordo", "pode sim", "com certeza"), acione IMEDIATAMENTE a ferramenta `accept_terms_and_conditions` com o `user_id` da sessão. Após o registro, apresente-se brevemente e pergunte como pode ajudar com a fazenda/pasto do usuário.

ATENÇÃO: Você NÃO PODE realizar diagnósticos, análises de pastagem ou cadastros de propriedades enquanto o usuário não aceitar os termos. Seu foco é estritamente coletar o aceite e tirar dúvidas sobre os termos. Use APENAS as ferramentas listadas abaixo.

TERMOS DE REFERÊNCIA (Use este texto APENAS para responder às perguntas do usuário sobre os termos, nunca o envie por inteiro):
Termos de Uso — Última atualização: 8 de março de 2026
1. Aceitação dos Termos: Ao acessar ou utilizar a plataforma Pasto Legal, o usuário declara que leu e concorda integralmente com estes Termos de Uso.
2. Descrição do Serviço: Plataforma de ciência aberta do LAPIG/UFG (com apoio do iCS e Solved). Oferece monitoramento da saúde de pastagens por satélite (Sentinel-2), análise de vigor vegetativo (NDVI, EVI), interação por IA via WhatsApp e acesso gratuito a dados/relatórios geoespaciais.
3. Cadastro e Acesso: Realizado pelo número de WhatsApp. O usuário consente com o processamento do número para fins de identificação e prestação do serviço (LGPD — Lei 13.709/2018).
4. Obrigações do Usuário: Fornecer informações verdadeiras, usar o serviço para finalidades lícitas, não fazer raspagem automatizada, respeitar limites de uso razoável, não usar dados para desmatamento ilegal.
5. Propriedade Intelectual: Código-fonte sob licença MIT. A marca "Pasto Legal" e identidade visual são da UFG/LAPIG. Dados geoespaciais de fontes públicas (Copernicus/ESA).
6. Limitação de Responsabilidade: Serviço "as is". UFG/LAPIG não garantem disponibilidade ininterrupta, não se responsabilizam por decisões tomadas com base exclusiva nos dados, nem garantem precisão absoluta dos dados de satélite. Recomenda-se uso como apoio à decisão.
7. Disponibilidade e Modificações: Serviço pode ser suspenso/modificado sem aviso prévio. Termos podem ser alterados periodicamente.
8. Lei Aplicável: Legislação brasileira (LGPD, Marco Civil da Internet, CDC). Foro de Goiânia/GO.
9. Contato: lapig.ufg@gmail.com
""".strip()


def build_onboarding_prompt(user_message: str, user_id: str = "", audio_input: bool = False) -> str:
    """Build the prompt for the first-time onboarding flow (terms acceptance).

    Ported from pi_rpc.py — unlike the normal flow, this injects the
    welcoming-agent instructions directly into the message (there is no
    documented per-request system-prompt override for /v1/responses either),
    lists ONLY onboarding tools, and skips Tool-RAG entirely.
    """
    from agent.registry import ONBOARDING_TOOLS, TOOLS as _REGISTRY

    name_to_tool = {t["name"]: t for t in _REGISTRY}

    parts = [_ONBOARDING_INSTRUCTIONS]

    if audio_input:
        parts.append(
            "## Resposta em áudio\n"
            "O usuário enviou esta mensagem como áudio. Responda normalmente em "
            "texto e DEPOIS chame a ferramenta `generate_speech` com o texto da "
            "sua resposta e o `user_id` da sessão, para que o usuário também "
            "receba a resposta em áudio falado.\n"
        )

    lines = []
    for name in ONBOARDING_TOOLS:
        t = name_to_tool.get(name)
        if t:
            lines.append(f"- `{name}`: {t['description']}")
    parts.append(
        "## Ferramentas disponíveis (Modo Onboarding)\n"
        "Use APENAS as ferramentas listadas abaixo. Não invente outras.\n\n"
        + "\n".join(lines) + "\n"
    )

    skill_lines = []
    for name in ONBOARDING_TOOLS:
        t = name_to_tool.get(name)
        if t and t.get("skill"):
            skill_lines.append(f"## Skill: {name}\n{t['skill']}")
    if skill_lines:
        parts.append("## Instruções específicas (skills)\n" + "\n\n".join(skill_lines) + "\n")

    parts.append("\n<session-state>")
    parts.append(f"<user-id>{user_id}</user-id>")
    parts.append("<terms-accepted>false</terms-accepted>")
    parts.append("</session-state>")
    parts.append(f"\n<user-message>{user_message}</user-message>")
    return "\n".join(parts)
