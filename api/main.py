"""
Pasto Legal — FastAPI application entry point.

Uses pi coding agent via JSON-RPC (--mode rpc) instead of AGNO.
The WhatsApp webhook communicates with a pi subprocess over stdin/stdout.
Python services (GEE, SICAR, TTS) remain unchanged.

Usage:
  uvicorn api.main:app --port 3000 --reload
"""
import os
import sys
import json
import base64
import subprocess
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.interfaces.whatsapp.router import attach_routes
from api.configs.config import config
from agent.pi_rpc import PiRpcPool

log = logging.getLogger("pasto-legal.main")
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(name)s | %(message)s")

CLI_DIR = Path(__file__).resolve().parent.parent / "agent" / "tools"

# ── pi RPC pool (per-user processes, started at startup) ──────────────
pi_pool: PiRpcPool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pi_pool
    provider = os.getenv("PI_PROVIDER", "google")
    model = os.getenv("PI_MODEL", "gemini-2.5-flash")
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
    pi_pool=pi_pool,
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


class ChatRequest(BaseModel):
    user_id: str = "streamlit-debug"
    message: str
    session_state: dict = {}

@app.post("/chat")
async def chat(req: ChatRequest):
    """Chat endpoint for Streamlit debug UI."""
    from agent.pi_rpc import build_prompt
    from agent.tool_rag import search_tools

    relevant_tools = search_tools(req.message, top_k=5)

    client = await pi_pool.get_client(req.user_id)
    full_prompt = build_prompt(
        req.message,
        user_id=req.user_id,
        session_state=req.session_state,
        relevant_tools=relevant_tools,
    )
    result = await client.prompt(full_prompt)
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
