"""
Pasto Legal — FastAPI application entry point.

Refactored to use pi coding agent (via Node.js bridge) instead of AGNO.
The WhatsApp webhook forwards messages to the bridge, which manages
conversation sessions, loads skills for each agent persona, and calls
Python CLI tools for domain-specific work (GEE, SICAR, TTS).

Usage:
  BRIDGE_URL=http://localhost:3001 uvicorn app.main:app --port 3000 --reload
"""
import os
import sys
import json
import base64
import subprocess
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.interfaces.whatsapp.router import attach_routes
from app.configs.config import config

log = logging.getLogger("pasto-legal.main")
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(name)s | %(message)s")

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:3001")
CLI_DIR = Path(__file__).resolve().parent.parent / "cli"

app = FastAPI(
    title="Pasto Legal",
    description="Assistente virtual para pecuaristas brasileiros via WhatsApp",
    version="2.0.0",
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
    bridge_url=BRIDGE_URL,
    access_token=config.WHATSAPP_ACCESS_TOKEN,
    phone_number_id=config.WHATSAPP_PHONE_NUMBER_ID,
    verify_token=config.WHATSAPP_VERIFY_TOKEN,
    enable_encryption=False,
)
app.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])


# ── Tool execution endpoint (called by pi bridge) ─────────────────────────

class ToolRequest(BaseModel):
    tool: str
    args: dict = {}

@app.post("/tool")
async def execute_tool(req: ToolRequest):
    """Execute a Python CLI tool and return the result.

    The pi bridge calls this endpoint instead of running Python directly
    (the bridge is a Node.js container without Python).
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
    return {"status": "ok", "bridge_url": BRIDGE_URL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", port=3000, reload=True)
