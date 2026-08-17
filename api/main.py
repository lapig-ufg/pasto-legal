"""
Pasto Legal — FastAPI application entry point.

Uses pi coding agent via JSON-RPC (--mode rpc) instead of AGNO.
The WhatsApp webhook communicates with a pi subprocess over stdin/stdout.
Python services (GEE, SICAR, TTS) remain unchanged.

Usage:
  uvicorn api.main:app --port 3000 --reload
"""
import os
import re
import sys
import json
import base64
import subprocess
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.interfaces.whatsapp.router import attach_routes
from api.configs.config import config
from api.services.audio.stt import transcribe_audio
from agent.pi_rpc import PiRpcPool, SESSIONS_DIR

log = logging.getLogger("pasto-legal.main")

CLI_DIR = Path(__file__).resolve().parent.parent / "agent" / "tools"

# ── pi RPC pool (per-user processes, started at startup) ──────────────
pi_pool: PiRpcPool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pi_pool
    provider = os.getenv("PI_PROVIDER", "google")
    model = os.getenv("PI_MODEL", "gemini-3.5-flash-lite")
    pi_pool = PiRpcPool(
        ttl=int(os.getenv("PI_SESSION_TTL", "1800")),
        provider=provider,
        model=model,
        cwd=str(Path(__file__).resolve().parent.parent / "agent"),
    )
    await pi_pool.start()
    log.info(f"[main] pi rpc pool started  provider={provider}  model={model}")
    yield
    await pi_pool.stop()


app = FastAPI(
    title="Pasto Legal",
    description="Assistente virtual para pecuaristas brasileiros via WhatsApp",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WhatsApp webhook ──────────────────────────────────────────────────────
whatsapp_router = attach_routes(
    access_token=config.WHATSAPP_ACCESS_TOKEN,
    phone_number_id=config.WHATSAPP_PHONE_NUMBER_ID,
    verify_token=config.WHATSAPP_VERIFY_TOKEN,
    enable_encryption=False,
)
app.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])


# ── Tool execution endpoint (called by pi custom tools) ─────────────────────────

class ToolRequest(BaseModel):
    tool: str
    args: dict = {}

@app.post("/tool")
async def execute_tool(req: ToolRequest):
    """Execute a Python CLI tool and return the result.

    Called by pi's custom tools (pasto-legal extension) via HTTP.
    pi runs in the same container, so localhost works.
    """
    tool = req.tool
    args = req.args
    script = CLI_DIR / f"{tool}.py"

    log.info(f"[tool] → {tool}  args={str(args)[:200]}")

    if not script.exists():
        log.error(f"[tool] ← {tool}  SCRIPT NOT FOUND: {script}")
        return {"error": f"Tool script not found: {tool}.py"}

    args_json = base64.b64encode(json.dumps(args, default=str).encode()).decode()

    try:
        result = subprocess.run(
            [sys.executable, str(script), args_json],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(CLI_DIR.parent),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if result.returncode != 0:
            log.error(f"[tool] ← {tool}  EXIT={result.returncode}  stderr={result.stderr[:300]}")
            return {"error": result.stderr.strip() or f"Exit code {result.returncode}"}

        output = json.loads(result.stdout)
        log.info(f"[tool] ← {tool}  ok  keys={list(output.keys())}")
        return output

    except subprocess.TimeoutExpired:
        log.error(f"[tool] ← {tool}  TIMEOUT")
        return {"error": "Tool execution timed out (120s)"}
    except json.JSONDecodeError as e:
        log.error(f"[tool] ← {tool}  INVALID JSON: {e}")
        return {"error": f"Invalid JSON from tool: {e}"}
    except Exception as e:
        log.error(f"[tool] ← {tool}  EXCEPTION: {e}")
        return {"error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok", "pi_pool": pi_pool is not None, "clients": len(pi_pool._clients) if pi_pool else 0}


class MediaItem(BaseModel):
    data: str = Field(..., description="base64-encoded media bytes")
    mime_type: str = Field("application/octet-stream")


class ChatRequest(BaseModel):
    user_id: str = "streamlit-debug"
    message: str
    session_state: dict = {}
    images: list[MediaItem] = Field(default_factory=list)
    audio: list[MediaItem] = Field(default_factory=list)
    recent_queries: list[str] = Field(default_factory=list)


def _prepare_media(req: ChatRequest) -> tuple[str, list[dict], bool]:
    """Transcribe audio clips into text and build the pi image list.

    Returns ``(message, images, audio_input)`` where ``audio_input`` is True
    when at least one audio clip was successfully transcribed — the caller
    uses it to instruct the LLM to reply with speech too.
    """
    message = req.message
    audio_input = False

    if req.audio:
        transcripts: list[str] = []
        for item in req.audio:
            try:
                raw = base64.b64decode(item.data)
            except Exception as e:
                log.warning(f"[chat] bad audio base64: {e}")
                continue
            text = transcribe_audio(raw, mime_type=item.mime_type)
            if text:
                transcripts.append(text)
                audio_input = True
            else:
                transcripts.append("[áudio não reconhecido]")
        if transcripts:
            joined = " ".join(transcripts)
            message = f"{joined}\n{message}".strip() if message.strip() else joined

    images = [
        {"type": "image", "data": img.data, "mimeType": img.mime_type}
        for img in req.images
        if img.data
    ]
    return message, images, audio_input


_USER_MSG_RE = re.compile(r"<user-message>(.*)</user-message>", re.DOTALL)


def _cleanup_last_user_message(user_id: str) -> None:
    """Strip prompt scaffolding from the last role=user line in session.jsonl.

    pi stores the entire build_prompt() output (system instructions, tools,
    session-state, ...) as the user message text. We rewrite only the most
    recent user message, replacing its text with just the inner content of
    the trailing <user-message>...</user-message> tag. All other JSONL lines
    and all structural fields (id, parentId, timestamp) are preserved.
    Best-effort: any error is logged and swallowed so /chat still returns.
    """
    session_file = SESSIONS_DIR / user_id / "session.jsonl"
    if not session_file.exists():
        return
    try:
        lines = session_file.read_text(encoding="utf-8").splitlines(keepends=True)
        last_user_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if not lines[i].strip():
                continue
            obj = json.loads(lines[i])
            if (obj.get("type") == "message"
                    and obj.get("message", {}).get("role") == "user"):
                last_user_idx = i
                break
        if last_user_idx is None:
            return
        obj = json.loads(lines[last_user_idx])
        content = obj["message"]["content"]
        if not content or not isinstance(content, list):
            return
        text = content[0].get("text", "") if isinstance(content[0], dict) else ""
        m = _USER_MSG_RE.search(text)
        if not m:
            return
        content[0]["text"] = m.group(1)
        lines[last_user_idx] = json.dumps(obj, ensure_ascii=False) + "\n"
        session_file.write_text("".join(lines), encoding="utf-8")
        log.debug(f"[chat] cleaned last user message for {user_id}")
    except Exception as e:
        log.warning(f"[chat] failed to cleanup session.jsonl for {user_id}: {e}")


@app.post("/chat")
async def chat(req: ChatRequest):
    """Chat endpoint for Streamlit debug UI."""
    import time as _time
    from agent.pi_rpc import build_prompt, build_onboarding_prompt
    from agent.tool_rag import search_tools

    _t0 = _time.time()
    message, images, audio_input = _prepare_media(req)

    # ── Onboarding gate: check terms acceptance from DB ──────────────
    session_state = dict(req.session_state or {})
    log.info(f"[chat] user={req.user_id} session_state={session_state}")
    if not session_state.get("terms_accepted"):
        try:
            from api.database.session import SessionLocal
            from api.database.models import UserTermsAcceptance
            db = SessionLocal()
            try:
                record = db.query(UserTermsAcceptance).filter(
                    UserTermsAcceptance.user_id == req.user_id,
                    UserTermsAcceptance.accepted == True,
                ).first()
                session_state["terms_accepted"] = bool(record)
            finally:
                db.close()
        except Exception:
            session_state["terms_accepted"] = False

    # First-time users → onboarding prompt (only accept_terms tool)
    if not session_state.get("terms_accepted"):
        client = await pi_pool.get_client(req.user_id)
        full_prompt = build_onboarding_prompt(message, user_id=req.user_id, audio_input=audio_input)
        result = await client.prompt(full_prompt, images=images or None)
        # Persist any terms_accepted update from the tool
        for update in result.get("session_state_updates", []):
            if isinstance(update, dict):
                session_state.update(update)
        result["session_state"] = session_state
        result["transcribed_message"] = message if message != req.message else None
        log.info(f"[chat] onboarding user={req.user_id} elapsed={_time.time() - _t0:.1f}s")
        _cleanup_last_user_message(req.user_id)
        return result

    # Normal flow: Tool-RAG + full prompt
    relevant_tools = search_tools(message, top_k=5, recent_queries=req.recent_queries)

    client = await pi_pool.get_client(req.user_id)
    full_prompt = build_prompt(
        message,
        user_id=req.user_id,
        session_state=session_state,
        relevant_tools=relevant_tools,
        audio_input=audio_input,
    )
    log.info(f"[chat] user={req.user_id} full_prompt={full_prompt}")
    result = await client.prompt(full_prompt, images=images or None)
    for update in result.get("session_state_updates", []):
        if isinstance(update, dict):
            session_state.update(update)
    result["session_state"] = session_state
    result["transcribed_message"] = message if message != req.message else None
    log.info(f"[chat] user={req.user_id} elapsed={_time.time() - _t0:.1f}s")
    _cleanup_last_user_message(req.user_id)
    return result


class ResetRequest(BaseModel):
    user_id: str

@app.post("/reset")
async def reset(req: ResetRequest):
    """Reset a user's session — kills the pi process and clears saved state."""
    await pi_pool.delete_session(req.user_id)
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", port=3000, reload=True)
