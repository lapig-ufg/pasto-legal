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

# ── Session directory ────────────────────────────────────────────────────

SESSIONS_DIR = Path(os.getenv("PI_SESSIONS_DIR", "/tmp/pi-sessions"))


def _session_path(user_id: str) -> Path:
    """Path to the user's pi session JSONL file."""
    return SESSIONS_DIR / user_id / "session.jsonl"


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

        cmd = [
            "pi", "--mode", "rpc",
            "--session", str(session_file),
            "--provider", self.provider,
            "--model", self.model,
            "-e", str(Path(self.cwd) / ".pi" / "extensions" / "pasto-legal-tools.js"),
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

    async def _read_event(self) -> Optional[dict]:
        line = await self.proc.stdout.readline()
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
                        result["content"] = "Desculpa, houve um erro ao processar sua solicitação. Tente novamente."
                    break

                elif t == "response" and not event.get("success", True):
                    log.error(f"[pi-rpc:{self.user_id[:12]}] cmd error: {event.get('error')}")

            return result


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
        model: str = "gemini-2.5-flash",
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
) -> str:
    """Build the prompt for pi.

    - System prompt: handled by AGENTS.md (pi reads it from cwd).
    - Session state: injected every message (changes after tool calls).
    - user_id: injected so the LLM can pass it to tools.
    - History: NOT injected — pi manages it in its session file.
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
