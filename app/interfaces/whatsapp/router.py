"""
WhatsApp webhook router — pi RPC mode.

Forwards messages to a pi coding agent subprocess via JSON-RPC (stdin/stdout).
Valkey debouncing, media download, PII guardrails, and WhatsApp message sending
remain unchanged. Only the agent execution path is replaced with a local
subprocess call instead of an HTTP bridge.

Usage (internal):
    attach_routes(pi_rpc=..., access_token=..., ...)
"""
import os
import asyncio
import hashlib
import pickle
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from time import time
from typing import Optional
from uuid import uuid4
from contextlib import suppress

import redis

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.interfaces.whatsapp.security import validate_webhook_signature
from app.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    download_event_media_async,
    extract_message_content,
    send_whatsapp_message_async,
    typing_indicator_async,
    upload_and_send_media_async,
    Audio,
    Image,
)
from app.guardrails.pii_gate import check_pii, mensagem_bloqueio
from app.services.audio.tts import generate_speech
from app.configs.config import config

# ── Valkey (Redis) connection ────────────────────────────────────────────
VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))

valkey_client = redis.Redis(
    host=VALKEY_HOST,
    port=VALKEY_PORT,
    db=VALKEY_DB,
    decode_responses=True,
)

_LONG_SLEEP = 8
_SHORT_SLEEP = 4
_EXECUTION_MESSAGE = "Ainda estamos processando sua última mensagem. Por favor, aguarde..."
_ERROR_MESSAGE = "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde."
_SESSION_RESET_MESSAGE = "Nova conversa iniciada!"


class _DebouceStatus(str):
    PENDING = "pending"
    COMPLETE = "complete"


def _encrypt_phone(phone: str, key: bytes) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError("`cryptography` not installed.")
    nonce = hashlib.sha256(phone.encode()).digest()[:12]
    ct = AESGCM(key).encrypt(nonce, phone.encode(), None)
    return urlsafe_b64encode(nonce + ct).decode()


def _get_session_state(user_id: str) -> dict:
    """Load session state from Valkey + DB for the pi context."""
    raw = valkey_client.get(f"session:{user_id}")
    state = json.loads(raw) if raw else {}

    # Check terms acceptance from DB (first-access gate)
    if not state.get("terms_accepted"):
        try:
            from app.database.session import SessionLocal
            from app.database.models import UserTermsAcceptance
            db = SessionLocal()
            try:
                record = db.query(UserTermsAcceptance).filter(
                    UserTermsAcceptance.user_id == user_id,
                    UserTermsAcceptance.accepted == True,
                ).first()
                state["terms_accepted"] = bool(record)
            finally:
                db.close()
        except Exception:
            state["terms_accepted"] = False

    return state


def _set_session_state(user_id: str, state: dict) -> None:
    """Persist session state updates."""
    valkey_client.set(f"session:{user_id}", json.dumps(state, default=str))


def _get_history(user_id: str) -> list:
    """Load conversation history from Valkey."""
    raw = valkey_client.get(f"history:{user_id}")
    return json.loads(raw) if raw else []


def _append_history(user_id: str, role: str, content: str) -> None:
    """Append a message to conversation history (max 40 messages)."""
    history = _get_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > 40:
        history = history[-40:]
    valkey_client.set(f"history:{user_id}", json.dumps(history, default=str))


def attach_routes(
    pi_pool=None,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    verify_token: Optional[str] = None,
    media_timeout: int = 30,
    enable_encryption: bool = False,
    encryption_key: Optional[bytes] = None,
) -> APIRouter:
    router = APIRouter()
    config_wa = WhatsAppConfig.init(
        access_token=access_token,
        phone_number_id=phone_number_id,
        verify_token=verify_token,
        media_timeout=media_timeout,
    )

    @router.get("/webhook")
    async def verify_webhook(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if not config_wa.verify_token:
            raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN is not set")
        if mode == "subscribe" and token == config_wa.verify_token:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)
        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post("/webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        payload = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not validate_webhook_signature(payload, signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        body = await request.json()
        if body.get("object") != "whatsapp_business_account":
            return {"status": "ignored"}

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for message in change.get("value", {}).get("messages", []):
                    background_tasks.add_task(process_message, message, pi_pool, config_wa, enable_encryption, encryption_key)

        return {"status": "processing"}

    return router


async def process_message(
    message: dict,
    pi_pool,
    config_wa: WhatsAppConfig,
    enable_encryption: bool = False,
    encryption_key: Optional[bytes] = None,
):
    phone_number = message.get("from")
    if not phone_number:
        return

    user_id = _encrypt_phone(phone_number, encryption_key) if enable_encryption and encryption_key else phone_number
    timestamp = message.get("timestamp", str(int(time())))

    try:
        message_id = message.get("id")
        await typing_indicator_async(message_id, config_wa)

        parsed = extract_message_content(message)
        if parsed is None:
            msg_type = message.get("type", "unknown")
            label = "this message type" if msg_type == "unsupported" else msg_type.title()
            await send_whatsapp_message_async(phone_number, f"Sorry, {label} is not supported yet.", config_wa)
            return

        # ── Valkey debouncing (same as before) ──────────────────────────
        valkey_execution_lock = valkey_client.lock(
            f"debounce_lock:{user_id}", timeout=60, blocking=True, blocking_timeout=5
        )
        if not valkey_execution_lock.acquire():
            await send_whatsapp_message_async(phone_number, _EXECUTION_MESSAGE, config_wa)
            return

        valkey_client.hset(f"debounce_status:{user_id}", timestamp, _DebouceStatus.PENDING)
        old_ts = valkey_client.get(f"debounce_ts:{user_id}")
        if not old_ts or int(old_ts) <= int(timestamp):
            valkey_client.set(f"debounce_ts:{user_id}", timestamp)

        if parsed.text.strip().lower() == "/new":
            valkey_client.delete(f"debounce_status:{user_id}", f"debounce_msgs:{user_id}")
            valkey_client.delete(f"session:{user_id}")
            await pi_pool.delete_session(user_id)
            await send_whatsapp_message_async(phone_number, _SESSION_RESET_MESSAGE, config_wa)
            return

        valkey_execution_lock.release()

        # ── PII guardrail ───────────────────────────────────────────────
        pii_types = check_pii(parsed.text or "")
        if pii_types:
            pii_warning = mensagem_bloqueio(pii_types)
            if parsed.audio_id:
                try:
                    audio = generate_speech(pii_warning, user_id=user_id)
                    if audio and audio.filepath:
                        with open(audio.filepath, "rb") as f:
                            await upload_and_send_media_async(
                                [Audio(content=f.read(), mime_type="audio/ogg")],
                                "audio", phone_number, config_wa,
                            )
                            return
                except Exception:
                    pass
            await send_whatsapp_message_async(phone_number, pii_warning, config_wa)
            return

        # ── Media download ──────────────────────────────────────────────
        media_kwargs, skipped_media = await download_event_media_async(parsed, config_wa)

        msg_data = {
            "parsed": {"text": parsed.text, "image_id": parsed.image_id, "video_id": parsed.video_id,
                        "audio_id": parsed.audio_id, "doc_id": parsed.doc_id},
            "media_kwargs": {k: [{"mime_type": getattr(v, "mime_type", None)} for v in val]
                             for k, val in media_kwargs.items()},
            "skipped_media": skipped_media,
            "timestamp": timestamp,
        }
        valkey_client.rpush(f"debounce_msgs:{user_id}", pickle.dumps(msg_data).hex())
        valkey_client.hset(f"debounce_status:{user_id}", timestamp, _DebouceStatus.COMPLETE)

        await asyncio.sleep(_LONG_SLEEP if (message.get("type") == "image" and not message.get("caption")) else _SHORT_SLEEP)

        if not valkey_execution_lock.acquire():
            return

        latest_ts = valkey_client.get(f"debounce_ts:{user_id}")
        if latest_ts and latest_ts != timestamp:
            valkey_execution_lock.release()
            return

        # Wait for pending messages
        wait_loops = 0
        while wait_loops < 30:
            statuses = valkey_client.hvals(f"debounce_status:{user_id}")
            if not any(s == _DebouceStatus.PENDING for s in statuses):
                break
            await asyncio.sleep(1)
            wait_loops += 1
        valkey_client.delete(f"debounce_status:{user_id}")

        raw_msgs = valkey_client.lrange(f"debounce_msgs:{user_id}", 0, -1)
        valkey_client.delete(f"debounce_msgs:{user_id}")

        all_msgs = sorted(
            [pickle.loads(bytes.fromhex(m)) for m in raw_msgs],
            key=lambda x: int(x["timestamp"]),
        )

        final_text = ""
        for msg_item in all_msgs:
            final_text += msg_item.get("parsed", {}).get("text", "") + "\n"

        if skipped_media:
            final_text = "[Some media could not be downloaded]\n\n" + final_text

        # ── Call pi RPC (option 2a: per-user process, in-memory session) ──
        session_state = _get_session_state(user_id)

        from app.core.pi_rpc import build_prompt

        # ── Onboarding gate: handle ENTIRELY in Python ─────────────────
        # Don't involve the LLM — pi's coding-agent system prompt overrides
        # user-message instructions. We handle acceptance here directly.
        if not session_state.get("terms_accepted"):
            text_lower = final_text.strip().lower()
            acceptance_keywords = ["sim", "aceito", "concordo", "ok", "pode", "sim senhor",
                                   "sim senhora", "claro", "com certeza", "positivo",
                                   "yes", "aceitar", "termos", "li e aceito"]
            is_acceptance = any(kw in text_lower for kw in acceptance_keywords)

            if is_acceptance:
                try:
                    from cli.onboarding import accept_terms
                    result = accept_terms({"user_id": user_id})
                    if "error" in result:
                        log.error(f"[router] onboarding error: {result['error']}")
                        await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config_wa)
                        return
                    session_state["terms_accepted"] = True
                    await send_whatsapp_message_async(
                        phone_number,
                        result.get("message", "Termos de Uso aceitos! 🎉 O sistema está liberado para uso. Como posso ajudar?"),
                        config_wa,
                    )
                    return
                except Exception as e:
                    log.error(f"[router] onboarding exception: {e}")
                    await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config_wa)
                    return

            # Not an acceptance — don't call pi at all. Send pre-canned terms.
            await send_whatsapp_message_async(
                phone_number,
                "🌿 *Bem-vindo ao Pasto Legal!*\n\n"
                "Antes de começar, você precisa aceitar os *Termos de Uso* da plataforma.\n\n"
                "📄 Termos de Uso: https://pasto.legal/termos-de-uso\n\n"
                "Resumo:\n"
                "• Plataforma gratuita do LAPIG/UFG\n"
                "• Dados de satélite Copernicus/ESA\n"
                "• Código aberto (MIT)\n"
                "• Serviço 'as is'\n"
                "• Contato: lapig.ufg@gmail.com\n\n"
                "Digite *ACEITO* para concordar e começar a usar.",
                config_wa,
            )
            return

        # Get or create per-user pi client (pi loads session from disk)
        client = await pi_pool.get_client(user_id)

        full_prompt = build_prompt(final_text.strip(), user_id=user_id, session_state=session_state)

        try:
            pi_result = await client.prompt(full_prompt)
        except Exception as e:
            log.error(f"[router] pi_rpc.prompt failed: {e}")
            await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config_wa)
            return

        # ── Send response back to WhatsApp ──────────────────────────────
        content = pi_result.get("content", "")
        images = pi_result.get("images", [])
        audio_paths = pi_result.get("audio", [])

        # Send images
        for img_b64 in images:
            try:
                import base64 as b64
                img_data = b64.b64decode(img_b64)
                await upload_and_send_media_async(
                    [Image(content=img_data, mime_type="image/png")],
                    "image", phone_number, config_wa,
                    response_content=content,
                )
                content = ""  # Only caption first image
            except Exception as e:
                print(f"Error sending image: {e}")

        # Send audio
        for audio_path in audio_paths:
            try:
                with open(audio_path, "rb") as f:
                    await upload_and_send_media_async(
                        [Audio(content=f.read(), mime_type="audio/ogg")],
                        "audio", phone_number, config_wa,
                    )
            except Exception as e:
                print(f"Error sending audio: {e}")

        # Send text (if any remaining)
        if content:
            await send_whatsapp_message_async(phone_number, content, config_wa)

    except Exception as e:
        print(f"Error processing message: {e}")
        try:
            await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config_wa)
        except Exception:
            pass
    finally:
        if valkey_execution_lock.locked():
            with suppress(Exception):
                valkey_execution_lock.release()
