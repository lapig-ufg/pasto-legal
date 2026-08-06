"""
JSON-RPC client for pi coding agent (--mode rpc).

Option 2a: one pi process per user, in-memory session, DB mirror via get_entries.
pi manages context and compaction; we save entries to Valkey for durability.
"""
import json
import asyncio
import contextlib
import logging
import os
import time
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("pasto-legal.pi_rpc")

# ── System prompt (injected on first message for new users) ──────────────
SYSTEM_PROMPT = """
Você é o **Pasto Legal**, um assistente virtual para pecuaristas brasileiros,
desenvolvido pelo LAPIG/UFG. Você ajuda produtores rurais com:

1. **Análise de pastagens** – biomassa, vigor vegetativo (NDVI/LAPIG),
   classificação de uso do solo, idade do pasto, topografia, textura do solo.
2. **Cadastro de propriedades** – registro via código CAR/SICAR, coordenadas
   geográficas ou link do Google Maps.
3. **Dúvidas sobre a plataforma** – como usar, de onde vêm os dados, FAQs.
4. **Conversa informal** – acolhimento, saudações, pequenas conversas.

## Regra de acesso — NOVOS USUÁRIOS (terms_accepted = false)
Se o contexto da sessão indicar "terms_accepted": false, o usuário AINDA NÃO
aceitou os Termos de Uso. Neste caso, você DEVE:
- Ignorar QUALQUER outra solicitação do usuário.
- Apresentar-se brevemente como assistente do Pasto Legal (LAPIG/UFG).
- Informar o link dos Termos de Uso: https://pasto.legal/termos-de-uso
- Perguntar educadamente se o usuário concorda com os termos.
- Apenas quando o usuário responder SIM, ACEITO, CONCORDO (ou similar),
  chame a ferramenta `accept_terms_and_conditions`.
- NUNCA faça análises, cadastros ou responda outras perguntas antes do aceite.
- Se o usuário tiver dúvidas sobre os termos, responda com base neste resumo:
  Plataforma gratuita do LAPIG/UFG, usa dados de satélite Copernicus/ESA,
  código aberto (MIT), serviço "as is", contato lapig.ufg@gmail.com.

## Regras absolutas (todos os usuários)
- Comunique-se SEMPRE em português brasileiro, linguagem simples e acessível.
- Use formatação do WhatsApp: *negrito* com asteriscos, sem markdown.
- NUNCA diga que você é um robô, IA, chatbot ou modelo de linguagem.
- NUNCA cite termos técnicos de software (prompts, ferramentas, agentes, tokens).
- Seja conciso. Respostas curtas, parágrafos limpos.
- Use emojis com moderação.
- Se o usuário pedir áudio, responda em texto — o sistema converte depois.

## Estado da sessão
O estado do usuário (propriedades cadastradas, persona, humor) é passado
como contexto no início de cada mensagem, dentro de tags <session-state>.
Use essas informações para personalizar suas respostas.

## Ferramentas disponíveis
Use as ferramentas cadastradas para buscar dados de propriedades, gerar
imagens de satélite, calcular estatísticas de pastagem e sintetizar áudio.
""".strip()

# ── Session file helpers ──────────────────────────────────────────────────

def _entries_to_jsonl(entries: list, cwd: str, session_id: str) -> str:
    """Convert a list of session entries to a JSONL string with header."""
    header = json.dumps({
        "type": "session",
        "version": 3,
        "id": session_id,
        "timestamp": entries[0]["timestamp"] if entries else _now_iso(),
        "cwd": cwd,
    }, ensure_ascii=False)
    lines = [header]
    for e in entries:
        lines.append(json.dumps(e, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── PiRpcClient (one per user) ────────────────────────────────────────────

class PiRpcClient:
    """Manages a single pi --mode rpc subprocess for one user.

    Uses --no-session (in-memory). pi manages context and compaction.
    We mirror the session tree to Valkey via get_entries() for durability.
    """

    def __init__(
        self,
        user_id: str,
        provider: str = "google",
        model: str = "gemini-2.5-flash",
        cwd: Optional[str] = None,
    ):
        self.user_id = user_id
        self.provider = provider
        self.model = model
        self.cwd = cwd or os.getcwd()
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self.last_used = time.time()
        self._has_session = False  # True if restored from saved entries

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self, session_entries: list = None) -> None:
        """Spawn the pi subprocess.

        If session_entries is provided, writes them to a temp JSONL file
        and starts pi with --session to restore the in-memory tree.
        Otherwise starts with --no-session (fresh).
        """
        if self.proc and self.proc.returncode is None:
            return

        env = os.environ.copy()
        # pi expects GEMINI_API_KEY, not GOOGLE_API_KEY
        if "GOOGLE_API_KEY" in env and "GEMINI_API_KEY" not in env:
            env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]
        # Ensure tool backend URL is set (extension calls this from pi)
        if "TOOL_BACKEND_URL" not in env:
            env["TOOL_BACKEND_URL"] = "http://localhost:3000"

        if session_entries:
            self._has_session = True
            session_file = self._write_temp_session(session_entries)
            cmd = [
                "pi", "--mode", "rpc",
                "--session", session_file,
                "--provider", self.provider,
                "--model", self.model,
                "-e", str(Path(self.cwd) / ".pi" / "extensions" / "pasto-legal-tools.js"),
            ]
            log.info(f"[pi-rpc:{self.user_id[:12]}] restoring session  entries={len(session_entries)}")
        else:
            self._has_session = False
            cmd = [
                "pi", "--mode", "rpc", "--no-session",
                "--provider", self.provider,
                "--model", self.model,
                "-e", str(Path(self.cwd) / ".pi" / "extensions" / "pasto-legal-tools.js"),
            ]

        log.info(f"[pi-rpc:{self.user_id[:12]}] spawning: {' '.join(cmd)}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=env,
            limit=2**20,  # 1 MB buffer (default 64 KB too small for large tool results)
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
        """Read stderr in background for debugging."""
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                break
            log.debug(f"[pi-rpc:{self.user_id[:12]}] stderr: {line.decode(errors='replace').strip()}")

    def _write_temp_session(self, entries: list) -> str:
        """Write session entries to a temp JSONL file for pi to load."""
        session_id = entries[0].get("id", "restored") if entries else "restored"
        jsonl = _entries_to_jsonl(entries, self.cwd, session_id)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", prefix=f"pi-session-{self.user_id[:8]}-",
            delete=False, encoding="utf-8",
        )
        tmp.write(jsonl)
        tmp.flush()
        log.info(f"[pi-rpc:{self.user_id[:12]}] wrote session file: {tmp.name}  ({len(jsonl)} bytes)")
        return tmp.name

    # ── RPC primitives ──────────────────────────────────────────────────

    async def _send(self, cmd: dict) -> None:
        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode())
        await self.proc.stdin.drain()

    async def _read_event(self) -> Optional[dict]:
        line = await self.proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line.decode(errors="replace").strip())
        except json.JSONDecodeError:
            log.warning(f"[pi-rpc:{self.user_id[:12]}] unparseable: {line[:100]!r}")
            return None

    async def _read_until(self, target_type: str, command: str = None) -> Optional[dict]:
        """Read events until a matching response or target event."""
        while True:
            event = await self._read_event()
            if event is None:
                return None
            t = event.get("type")
            if t == target_type:
                return event
            if t == "response" and event.get("command") == command:
                return event
            if t == "response" and not event.get("success", True):
                log.error(f"[pi-rpc:{self.user_id[:12]}] cmd error: {event.get('error')}")

    # ── High-level API ──────────────────────────────────────────────────

    async def prompt(self, message: str, images: list = None) -> dict:
        """Send a prompt and collect the full response.

        pi manages conversation context from its in-memory session.
        We only send the current message + session state.
        """
        async with self._lock:
            self.last_used = time.time()

            cmd: dict = {"type": "prompt", "message": message}
            if images:
                cmd["images"] = images

            await self._send(cmd)

            result = {"content": "", "images": [], "audio": []}

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

                elif t == "tool_execution_start":
                    log.info(
                        f"[pi-rpc:{self.user_id[:12]}] tool start: {event.get('toolName')} "
                        f"args={json.dumps(event.get('args', {}), default=str)[:150]}"
                    )

                elif t == "tool_execution_end":
                    tool_name = event.get("toolName", "?")
                    is_error = event.get("isError", False)
                    tool_result = event.get("result", {})
                    details = tool_result.get("details", {})
                    # Log the full result for debugging
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
                                    # Already base64-encoded (from CLI scripts)
                                    result["images"].append(path)
                            except Exception as e:
                                log.error(f"[pi-rpc:{self.user_id[:12]}] image read failed: {path} — {e}")
                    if details.get("audioPath"):
                        result["audio"].append(details["audioPath"])

                elif t == "extension_error":
                    log.error(
                        f"[pi-rpc:{self.user_id[:12]}] extension error: "
                        f"path={event.get('extensionPath')} "
                        f"event={event.get('event')} "
                        f"error={event.get('error')}"
                    )

                elif t == "agent_settled":
                    log.info(f"[pi-rpc:{self.user_id[:12]}] settled  text_len={len(result['content'])}")
                    # Fallback: if LLM produced no text but tools ran, provide a default
                    if not result["content"].strip() and not result["images"] and not result["audio"]:
                        result["content"] = "Desculpa, houve um erro ao processar sua solicitação. Tente novamente."
                    break

                elif t == "response" and not event.get("success", True):
                    log.error(f"[pi-rpc:{self.user_id[:12]}] cmd error: {event.get('error')}")

            return result

    async def get_entries(self) -> dict:
        """Get the full session entry tree from pi's in-memory session.

        Returns the data portion of the get_entries response:
        {entries: [...], leafId: "..."}
        """
        async with self._lock:
            await self._send({"type": "get_entries"})
            resp = await self._read_until("response", "get_entries")
            if resp and resp.get("success"):
                return resp.get("data", {"entries": [], "leafId": None})
            return {"entries": [], "leafId": None}

    async def new_session(self) -> None:
        """Start a fresh session (for /new command)."""
        async with self._lock:
            self._has_session = False
            await self._send({"type": "new_session"})
            await self._read_until("response", "new_session")


# ── PiRpcPool ─────────────────────────────────────────────────────────────

class PiRpcPool:
    """Pool of per-user PiRpcClient instances with TTL-based cleanup.

    Each user gets their own pi process. Sessions are mirrored to Valkey
    after each prompt and restored on reconnection.
    """

    def __init__(
        self,
        ttl: int = 1800,  # 30 min idle before cleanup
        provider: str = "google",
        model: str = "gemini-2.5-flash",
        cwd: Optional[str] = None,
    ):
        self._clients: dict[str, PiRpcClient] = {}
        self._ttl = ttl
        self._provider = provider
        self._model = model
        self._cwd = cwd or os.getcwd()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop all clients and the cleanup task."""
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

        Restores session from Valkey if available.
        """
        # Return existing live client
        client = self._clients.get(user_id)
        if client and client.proc and client.proc.returncode is None:
            client.last_used = time.time()
            return client

        # Remove dead client
        if client:
            await client.stop()
            del self._clients[user_id]

        # Load saved session entries from Valkey
        entries = self._load_session(user_id)

        # Create and start new client
        client = PiRpcClient(
            user_id=user_id,
            provider=self._provider,
            model=self._model,
            cwd=self._cwd,
        )
        await client.start(session_entries=entries)
        self._clients[user_id] = client
        return client

    async def save_session(self, user_id: str) -> None:
        """Save the user's session entries to Valkey."""
        client = self._clients.get(user_id)
        if not client or not client.proc or client.proc.returncode is not None:
            return
        try:
            data = await client.get_entries()
            entries = data.get("entries", [])
            if entries:
                _valkey_set(f"pi_session:{user_id}", json.dumps(entries, default=str))
                log.info(f"[pool] saved session  user={user_id[:12]}  entries={len(entries)}")
        except Exception as e:
            log.error(f"[pool] save session failed  user={user_id[:12]}: {e}")

    def _load_session(self, user_id: str) -> Optional[list]:
        """Load saved session entries from Valkey."""
        try:
            raw = _valkey_get(f"pi_session:{user_id}")
            if raw:
                entries = json.loads(raw)
                log.info(f"[pool] loaded session  user={user_id[:12]}  entries={len(entries)}")
                return entries
        except Exception as e:
            log.error(f"[pool] load session failed  user={user_id[:12]}: {e}")
        return None

    async def delete_session(self, user_id: str) -> None:
        """Delete a user's session (for /new command)."""
        client = self._clients.pop(user_id, None)
        if client:
            await client.stop()
        try:
            _valkey_delete(f"pi_session:{user_id}")
        except Exception:
            pass

    async def _cleanup_loop(self) -> None:
        """Periodically clean up idle clients."""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            now = time.time()
            for user_id in list(self._clients):
                client = self._clients.get(user_id)
                if client and now - client.last_used > self._ttl:
                    log.info(f"[pool] cleaning up idle  user={user_id[:12]}")
                    await self.save_session(user_id)
                    await client.stop()
                    del self._clients[user_id]


# ── Valkey helpers (lazy import to avoid circular deps) ──────────────────

def _valkey_client():
    import redis
    host = os.getenv("VALKEY_HOST", "localhost")
    port = int(os.getenv("VALKEY_PORT", "6379"))
    db = int(os.getenv("VALKEY_DB", "0"))
    return redis.Redis(host=host, port=port, db=db, decode_responses=True)


def _valkey_get(key: str) -> Optional[str]:
    try:
        return _valkey_client().get(key)
    except Exception:
        return None


def _valkey_set(key: str, value: str) -> None:
    try:
        _valkey_client().set(key, value)
    except Exception:
        pass


def _valkey_delete(key: str) -> None:
    try:
        _valkey_client().delete(key)
    except Exception:
        pass


# ── Prompt builder ─────────────────────────────────────────────────────────

def build_prompt(
    user_message: str,
    user_id: str = "",
    session_state: dict = None,
    is_new_session: bool = False,
) -> str:
    """Build the prompt for pi.

    - System prompt: handled by AGENTS.md (pi reads it from cwd).
    - Session state: injected every message (it changes after tool calls).
    - user_id: injected so the LLM can pass it to tools.
    - History: NOT injected — pi manages it in its in-memory session.
    """
    parts = []

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

    parts.append("</session-state>")

    parts.append(f"\n<user-message>{user_message}</user-message>")
    return "\n".join(parts)
