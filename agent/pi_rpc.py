"""
JSON-RPC client for pi coding agent (--mode rpc).

Native session management: pi writes session files directly to disk.
No Valkey mirror, no get_entries, no temp JSONL — pi owns its files.
"""
import json
import asyncio
import contextlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("pasto-legal.pi_rpc")
metrics_log = logging.getLogger("pasto-legal.run_metrics")

# ── Session directory ────────────────────────────────────────────────────

SESSIONS_DIR = Path(os.getenv("PI_SESSIONS_DIR", "/tmp/pi-sessions"))


def _session_path(user_id: str) -> Path:
    """Path to the user's pi session JSONL file."""
    return SESSIONS_DIR / user_id / "session.jsonl"


def _read_last_usage(session_file: Path) -> Optional[dict]:
    """Read the most recent assistant usage block from a pi session JSONL.

    pi writes one JSON object per line. Assistant turns carry a ``usage``
    block (input/output/reasoning/totalTokens/cost). We scan the file
    sequentially and keep the last entry that has one — cheap enough for
    the small session files produced per user.
    """
    if not session_file.exists():
        return None
    last_usage: Optional[dict] = None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message") or {}
                if msg.get("role") != "assistant":
                    continue
                usage = msg.get("usage")
                if usage:
                    last_usage = {
                        "input_tokens": usage.get("input", 0),
                        "output_tokens": usage.get("output", 0),
                        "reasoning_tokens": usage.get("reasoning", 0),
                        "cache_read_tokens": usage.get("cacheRead", 0),
                        "cache_write_tokens": usage.get("cacheWrite", 0),
                        "total_tokens": usage.get("totalTokens", 0),
                        "cost_total": (usage.get("cost") or {}).get("total", 0.0),
                        "cost_input": (usage.get("cost") or {}).get("input", 0.0),
                        "cost_output": (usage.get("cost") or {}).get("output", 0.0),
                        "stop_reason": msg.get("stopReason"),
                        "model": msg.get("model"),
                        "provider": msg.get("provider"),
                    }
    except OSError as e:
        log.warning(f"[pi-rpc] failed to read usage from {session_file}: {e}")
    return last_usage


# ── PiRpcClient (one per user) ────────────────────────────────────────────

class PiRpcClient:
    """Manages a single pi --mode rpc subprocess for one user.

    pi writes its session to a JSONL file on disk. Compaction, branching,
    and tree structure are all handled natively by pi.
    """

    def __init__(
        self,
        user_id: str,
        provider: str = "google",
        model: str = "gemini-3.5-flash-lite",
        cwd: Optional[str] = None,
    ):
        self.user_id = user_id
        self.provider = provider
        self.model = model
        self.cwd = cwd or os.getcwd()
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self.last_used = time.time()

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the pi subprocess with --session pointing to its JSONL file.

        If the file exists, pi loads and continues it. If not, pi creates a new one.
        """
        if self.proc and self.proc.returncode is None:
            return

        session_file = _session_path(self.user_id)
        session_file.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        if "GOOGLE_API_KEY" in env and "GEMINI_API_KEY" not in env:
            env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]
        if "TOOL_BACKEND_URL" not in env:
            env["TOOL_BACKEND_URL"] = "http://localhost:3000"

        # Prompt-dumper extension: tell it where to write last_prompt.{json,md}
        # for this user. The extension is a no-op unless PI_DUMP_PROMPT is set.
        env["PI_DUMP_DIR"] = str(session_file.parent)
        env["PI_DUMP_USER_ID"] = self.user_id

        log.info(env)

        cmd = [
            "pi", "--mode", "rpc",
            "--session", str(session_file),
            "--provider", self.provider,
            "--model", self.model,
            "-e", str(Path(self.cwd) / "extensions" / "pasto-legal-tools.js"),
            "-e", str(Path(self.cwd) / "extensions" / "strip-history.js"),
            "-e", str(Path(self.cwd) / "extensions" / "prompt-dumper.js"),
        ]

        is_new = not session_file.exists()
        log.info(
            f"[pi-rpc:{self.user_id[:12]}] spawning: {' '.join(cmd)}  "
            f"({'new' if is_new else 'existing'})"
        )
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=env,
            limit=2**20,
        )
        log.info(f"[pi-rpc:{self.user_id[:12]}] started pid={self.proc.pid}")
        asyncio.create_task(self._drain_stderr())

    async def stop(self) -> None:
        """Terminate the pi subprocess."""
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            log.info(f"[pi-rpc:{self.user_id[:12]}] stopped")
        self.proc = None

    async def _drain_stderr(self) -> None:
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                break
            log.debug(f"[pi-rpc:{self.user_id[:12]}] stderr: {line.decode(errors='replace').strip()}")

    # ── RPC primitives ──────────────────────────────────────────────────

    async def _send(self, cmd: dict) -> None:
        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode())
        await self.proc.stdin.drain()

    async def _read_event(self, timeout: float = 600.0) -> Optional[dict]:
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            log.error(f"[pi-rpc:{self.user_id[:12]}] readline timed out after {timeout}s")
            return None
        if not line:
            return None
        try:
            return json.loads(line.decode(errors="replace").strip())
        except json.JSONDecodeError:
            log.warning(f"[pi-rpc:{self.user_id[:12]}] unparseable: {line[:100]!r}")
            return None

    # ── High-level API ──────────────────────────────────────────────────

    async def prompt(self, message: str, images: list = None) -> dict:
        """Send a prompt and collect the full response.

        pi manages conversation context from its session file.
        We only send the current message + session state.
        """
        async with self._lock:
            self.last_used = time.time()
            _t0 = time.time()
            _tool_calls = 0

            cmd: dict = {"type": "prompt", "message": message}
            if images:
                cmd["images"] = images

            await self._send(cmd)

            result = {"content": "", "images": [], "audio": [], "session_state_updates": []}
            last_stop_reason: Optional[str] = None
            last_error_msg: Optional[str] = None

            while True:
                event = await self._read_event()
                if event is None:
                    log.error(f"[pi-rpc:{self.user_id[:12]}] unexpected EOF")
                    break

                t = event.get("type")

                if t == "message_update":
                    delta = event.get("assistantMessageEvent", {})
                    if delta.get("type") == "text_delta":
                        result["content"] += delta.get("delta", "")
                    if "stopReason" in delta:
                        last_stop_reason = delta.get("stopReason")
                    if delta.get("errorMessage"):
                        last_error_msg = delta.get("errorMessage")

                elif t == "tool_execution_start":
                    log.info(
                        f"[pi-rpc:{self.user_id[:12]}] tool start: {event.get('toolName')} "
                        f"args={json.dumps(event.get('args', {}), default=str)[:150]}"
                    )

                elif t == "tool_execution_end":
                    _tool_calls += 1
                    tool_name = event.get("toolName", "?")
                    is_error = event.get("isError", False)
                    tool_result = event.get("result", {})
                    details = tool_result.get("details", {})
                    result_preview = json.dumps(tool_result, default=str)[:300]
                    log.info(
                        f"[pi-rpc:{self.user_id[:12]}] tool end: {tool_name} "
                        f"isError={is_error} result={result_preview}"
                    )
                    if details.get("imagePaths"):
                        for path in details["imagePaths"]:
                            try:
                                import base64 as _b64
                                if os.path.isfile(path):
                                    with open(path, "rb") as f:
                                        result["images"].append(_b64.b64encode(f.read()).decode())
                                else:
                                    result["images"].append(path)
                            except Exception as e:
                                log.error(f"[pi-rpc:{self.user_id[:12]}] image read failed: {path} — {e}")
                    if details.get("audioPath"):
                        result["audio"].append(details["audioPath"])
                    if details.get("sessionState"):
                        result["session_state_updates"].append(details["sessionState"])

                elif t == "extension_error":
                    log.error(
                        f"[pi-rpc:{self.user_id[:12]}] extension error: "
                        f"path={event.get('extensionPath')} "
                        f"event={event.get('event')} "
                        f"error={event.get('error')}"
                    )

                elif t == "agent_settled":
                    log.info(f"[pi-rpc:{self.user_id[:12]}] settled  text_len={len(result['content'])}")
                    if not result["content"].strip() and not result["images"] and not result["audio"]:
                        if last_error_msg:
                            log.error(
                                f"[pi-rpc:{self.user_id[:12]}] empty reply — "
                                f"stopReason={last_stop_reason} error={last_error_msg[:500]}"
                            )
                        elif last_stop_reason:
                            log.error(
                                f"[pi-rpc:{self.user_id[:12]}] empty reply — "
                                f"stopReason={last_stop_reason}"
                            )
                        else:
                            log.error(f"[pi-rpc:{self.user_id[:12]}] empty reply — no stop reason")
                        result["content"] = "Desculpa, houve um erro ao processar sua solicitação. Tente novamente."
                    break

                elif t == "response" and not event.get("success", True):
                    log.error(f"[pi-rpc:{self.user_id[:12]}] cmd error: {event.get('error')}")

            self._log_run_metrics(result, _t0, _tool_calls, last_stop_reason)
            return result

    def _log_run_metrics(
        self,
        result: dict,
        t0: float,
        tool_calls: int,
        stop_reason: Optional[str],
    ) -> None:
        """Emit a debug log with run metrics (duration, tokens, cost, ...).

        Token/cost data is read from the pi session JSONL, where pi writes
        a ``usage`` block on every assistant turn.
        """
        elapsed = time.time() - t0
        usage = _read_last_usage(_session_path(self.user_id))
        metrics = {
            "user_id": self.user_id,
            "model": (usage or {}).get("model") or self.model,
            "provider": (usage or {}).get("provider") or self.provider,
            "elapsed_s": round(elapsed, 3),
            "input_tokens": (usage or {}).get("input_tokens", 0),
            "output_tokens": (usage or {}).get("output_tokens", 0),
            "reasoning_tokens": (usage or {}).get("reasoning_tokens", 0),
            "cache_read_tokens": (usage or {}).get("cache_read_tokens", 0),
            "cache_write_tokens": (usage or {}).get("cache_write_tokens", 0),
            "total_tokens": (usage or {}).get("total_tokens", 0),
            "cost_total": (usage or {}).get("cost_total", 0.0),
            "cost_input": (usage or {}).get("cost_input", 0.0),
            "cost_output": (usage or {}).get("cost_output", 0.0),
            "stop_reason": (usage or {}).get("stop_reason") or stop_reason,
            "content_len": len(result.get("content", "")),
            "n_images": len(result.get("images", [])),
            "n_audio": len(result.get("audio", [])),
            "n_tool_calls": tool_calls,
        }
        result["metrics"] = metrics
        metrics_log.debug("run_metrics " + json.dumps(metrics, ensure_ascii=False))


# ── PiRpcPool ─────────────────────────────────────────────────────────────

class PiRpcPool:
    """Pool of per-user PiRpcClient instances with TTL-based cleanup.

    Each user gets their own pi process writing to its own session file.
    pi handles all session persistence natively — no Valkey mirror needed.
    """

    def __init__(
        self,
        ttl: int = 1800,
        provider: str = "google",
        model: str = "gemini-3.5-flash-lite",
        cwd: Optional[str] = None,
    ):
        self._clients: dict[str, PiRpcClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl = ttl
        self._provider = provider
        self._model = model
        self._cwd = cwd or os.getcwd()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        for user_id in list(self._clients):
            client = self._clients.pop(user_id, None)
            if client:
                await client.stop()

    async def get_client(self, user_id: str) -> PiRpcClient:
        """Get or create a pi client for a user.

        Uses a per-user lock to prevent race conditions where two concurrent
        requests for the same user both create new processes.
        """
        # Per-user lock to prevent duplicate process creation
        lock = self._locks.get(user_id)
        if not lock:
            lock = asyncio.Lock()
            self._locks[user_id] = lock

        async with lock:
            # Return existing live client
            client = self._clients.get(user_id)
            if client and client.proc and client.proc.returncode is None:
                client.last_used = time.time()
                return client

            # Remove dead client
            if client:
                await client.stop()
                del self._clients[user_id]

            # Create and start new client (pi loads session from disk)
            client = PiRpcClient(
                user_id=user_id,
                provider=self._provider,
                model=self._model,
                cwd=self._cwd,
            )
            await client.start()
            self._clients[user_id] = client
            return client

    async def delete_session(self, user_id: str) -> None:
        """Delete a user's session file and stop their pi process."""
        # Lock to prevent concurrent get_client from recreating
        lock = self._locks.get(user_id)
        if not lock:
            lock = asyncio.Lock()
            self._locks[user_id] = lock

        async with lock:
            client = self._clients.pop(user_id, None)
            if client:
                await client.stop()
            try:
                session_file = _session_path(user_id)
                if session_file.exists():
                    session_file.unlink()
                    log.info(f"[pool] deleted session file  user={user_id[:12]}")
            except Exception as e:
                log.error(f"[pool] delete session failed  user={user_id[:12]}: {e}")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up idle clients. pi already wrote to disk."""
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for user_id in list(self._clients):
                client = self._clients.get(user_id)
                if client and now - client.last_used > self._ttl:
                    log.info(f"[pool] cleaning up idle  user={user_id[:12]}")
                    await client.stop()
                    del self._clients[user_id]


# ── Prompt builder ─────────────────────────────────────────────────────────

def build_prompt(
    user_message: str,
    user_id: str = "",
    session_state: dict = None,
    relevant_tools: list[str] | None = None,
    audio_input: bool = False,
) -> str:
    """Build the prompt for pi.

    - System prompt: handled by AGENTS.md (pi reads it from cwd).
    - Session state: injected every message (changes after tool calls).
    - user_id: injected so the LLM can pass it to tools.
    - relevant_tools: if provided, only these tools are suggested to the LLM
      (Zero Prompt Bloat — RAG-selected tools only).
    - audio_input: when True, the user sent an audio message — instruct the
      LLM to also call `generate_speech` so the reply comes back as audio.
    - History: NOT injected — pi manages it in its session file.
    """
    parts = []

    # ── Audio-input directive: respond with speech ─────────────────────
    if audio_input:
        parts.append(
            "## Resposta em áudio\n"
            "O usuário enviou esta mensagem como áudio. Responda normalmente em "
            "texto e DEPOIS chame a ferramenta `generate_speech` com o texto da "
            "sua resposta e o `user_id` da sessão, para que o usuário também "
            "receba a resposta em áudio falado.\n"
        )

    # ── Tool-RAG: only suggest relevant tools + inject skills ─────────
    if relevant_tools:
        from agent.registry import TOOLS as _REGISTRY
        name_to_tool = {t["name"]: t for t in _REGISTRY}

        # Tool descriptions
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

        # Skill instructions (only for tools that have them)
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


# ── Onboarding prompt (first-time terms acceptance) ───────────────────────

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

    Unlike the normal flow, this:
    - Injects welcoming-agent instructions directly into the message (pi's
      AGENTS.md system prompt is not overridable per-prompt in RPC mode).
    - Lists ONLY onboarding tools (accept_terms_and_conditions, generate_speech).
    - Skips Tool-RAG entirely.
    - Marks terms_accepted as false in session-state.
    - When audio_input is True, instructs the LLM to also call generate_speech
      so the reply comes back as audio (user sent audio).

    Once the user accepts and the LLM calls `accept_terms_and_conditions`, the
    tool writes to the database. The next message's session-state lookup will
    find terms_accepted=True and route to the normal flow.
    """
    from agent.registry import ONBOARDING_TOOLS, TOOLS as _REGISTRY

    name_to_tool = {t["name"]: t for t in _REGISTRY}

    parts = [_ONBOARDING_INSTRUCTIONS]

    # ── Audio-input directive: respond with speech ─────────────────────
    if audio_input:
        parts.append(
            "## Resposta em áudio\n"
            "O usuário enviou esta mensagem como áudio. Responda normalmente em "
            "texto e DEPOIS chame a ferramenta `generate_speech` com o texto da "
            "sua resposta e o `user_id` da sessão, para que o usuário também "
            "receba a resposta em áudio falado.\n"
        )

    # Onboarding tools only
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

    # Skill instructions for onboarding tools
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
