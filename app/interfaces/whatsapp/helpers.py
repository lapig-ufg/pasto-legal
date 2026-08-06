import io
import logging
import mimetypes
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Union

import httpx

# ── Logging (replaces agno.utils.log) ────────────────────────────────────
log = logging.getLogger("pasto-legal.whatsapp")

def log_error(msg: str) -> None:
    log.error(msg)

def log_info(msg: str) -> None:
    log.info(msg)

def log_warning(msg: str) -> None:
    log.warning(msg)

# ── Media dataclasses (replaces agno.media) ───────────────────────────────

@dataclass
class Image:
    content: bytes
    mime_type: Optional[str] = None

    async def aget_content_bytes(self) -> bytes:
        return self.content

@dataclass
class Video:
    content: bytes
    mime_type: Optional[str] = None

    async def aget_content_bytes(self) -> bytes:
        return self.content

@dataclass
class Audio:
    content: bytes
    mime_type: Optional[str] = None
    transcript: Optional[str] = None
    filepath: Optional[str] = None
    channels: int = 1
    sample_rate: int = 24000
    format: Optional[str] = None

    async def aget_content_bytes(self) -> bytes:
        if self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        return self.content

@dataclass
class File:
    content: bytes
    mime_type: Optional[str] = None
    name: Optional[str] = None
    filename: Optional[str] = None

    async def aget_content_bytes(self) -> bytes:
        return self.content

# ── Image type detection (replaces agno.utils.media.get_image_type) ───────

_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # simplified; full check would look for WEBP in chunk
}

def get_image_type(data: bytes) -> Optional[str]:
    for sig, fmt in _IMAGE_SIGNATURES.items():
        if data[:len(sig)] == sig:
            return fmt
    return None

# ── PCM to WAV (replaces agno.utils.audio.pcm_to_wav_bytes) ──────────────

def pcm_to_wav_bytes(pcm_data: bytes, channels: int = 1, rate: int = 24000) -> bytes:
    """Wrap raw PCM 16-bit mono audio in a WAV container."""
    sample_width = 2  # 16-bit
    byte_rate = rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm_data)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,          # chunk size
        1,           # PCM format
        channels,
        rate,
        byte_rate,
        block_align,
        sample_width * 8,  # bits per sample
        b"data",
        data_size,
    )
    return header + pcm_data

# ── WhatsApp API config ──────────────────────────────────────────────────

_BASE_URL = "https://graph.facebook.com"
_API_VERSION = "v22.0"


@dataclass
class WhatsAppConfig:
    access_token: str
    phone_number_id: str
    verify_token: Optional[str] = None
    media_timeout: int = 30

    @classmethod
    def init(
        cls,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
        media_timeout: int = 30,
    ) -> "WhatsAppConfig":
        token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        v_token = verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN")
        if not token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not set.")
        if not phone_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not set.")
        return cls(access_token=token, phone_number_id=phone_id, verify_token=v_token, media_timeout=media_timeout)

    def messages_url(self) -> str:
        return f"{_BASE_URL}/{_API_VERSION}/{self.phone_number_id}/messages"

    def media_url(self) -> str:
        return f"{_BASE_URL}/{_API_VERSION}/{self.phone_number_id}/media"

    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass
class MessageContent:
    text: str
    image_id: Optional[str] = None
    video_id: Optional[str] = None
    audio_id: Optional[str] = None
    doc_id: Optional[str] = None


def extract_message_content(message: dict) -> Optional[MessageContent]:
    log_info(str(message))
    msg_type = message.get("type")

    if msg_type == "text":
        text = message["text"]["body"]
        return MessageContent(text=text)

    if msg_type == "location":
        latitude = message["location"]["latitude"]
        longitude = message["location"]["longitude"]
        return MessageContent(
            text=f"Quero registrar minha propriedade nas coordenadas Lat: {latitude} Long: {longitude}.",
        )

    if msg_type == "image":
        return MessageContent(
            text=message.get("image", {}).get("caption", ""),
            image_id=message["image"]["id"],
        )

    if msg_type == "video":
        return MessageContent(
            text=message.get("video", {}).get("caption", ""),
            video_id=message["video"]["id"],
        )

    if msg_type == "audio":
        return MessageContent(text="", audio_id=message["audio"]["id"])

    if msg_type == "document":
        return MessageContent(
            text=message.get("document", {}).get("caption", ""),
            doc_id=message["document"]["id"],
        )

    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            return MessageContent(text=reply.get("title", ""))
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            text = reply.get("title", "")
            description = reply.get("description", "")
            if description:
                text = f"{text}: {description}"
            return MessageContent(text=text)
        log_warning(f"Unknown interactive type: {interactive_type}")
        return None

    log_warning(f"Unknown message type: {msg_type}")
    return None


_WHATSAPP_AUDIO_MIMES = {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg", "audio/wav"}


@dataclass
class _MediaResult:
    content: Optional[bytes] = None
    mime_type: Optional[str] = None
    skip_reason: Optional[str] = None


async def _download_media(media_id: str, media_label: str, config: WhatsAppConfig) -> _MediaResult:
    url = f"{_BASE_URL}/{_API_VERSION}/{media_id}"
    headers = config.auth_headers()
    timeout = config.media_timeout
    mime_type: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            metadata = resp.json()
        media_url = metadata.get("url")
        mime_type = metadata.get("mime_type")
    except httpx.HTTPError as e:
        reason = f"{media_label} (metadata fetch failed: {e})"
        log_warning(f"Media download skipped: {reason}")
        return _MediaResult(skip_reason=reason)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(media_url, headers=headers)
            resp.raise_for_status()
            return _MediaResult(content=resp.content, mime_type=mime_type)
    except httpx.HTTPError as e:
        reason = f"{media_label} (download failed: {e})"
        log_warning(f"Media download skipped: {reason}")
        return _MediaResult(skip_reason=reason)


_MEDIA_FIELDS = ("image_id", "video_id", "audio_id", "doc_id")
_MEDIA_LABELS = ("image", "video", "audio", "document")


async def download_event_media_async(parsed: "MessageContent", config: WhatsAppConfig) -> Tuple[dict, List[str]]:
    run_kwargs: dict = {}
    skipped: List[str] = []

    for field_name, label in zip(_MEDIA_FIELDS, _MEDIA_LABELS):
        media_id = getattr(parsed, field_name, None)
        if not media_id:
            continue
        result = await _download_media(media_id, label, config)
        if result.skip_reason:
            skipped.append(result.skip_reason)
            continue
        content = result.content
        mime = result.mime_type
        if label == "image":
            run_kwargs["images"] = [Image(content=content, mime_type=mime)]
        elif label == "video":
            run_kwargs["videos"] = [Video(content=content, mime_type=mime)]
        elif label == "audio":
            run_kwargs["audio"] = [Audio(content=content, mime_type=mime)]
        elif label == "document":
            run_kwargs["files"] = [File(content=content, mime_type=mime)]

    return run_kwargs, skipped


async def upload_media_async(
    media_data: bytes, mime_type: str, filename: str, config: WhatsAppConfig
) -> Union[str, dict]:
    url = config.media_url()
    headers = config.auth_headers()
    data = {"messaging_product": "whatsapp", "type": mime_type}

    try:
        file_data = io.BytesIO(media_data)
        files = {"file": (filename, file_data, mime_type)}
        async with httpx.AsyncClient(timeout=config.media_timeout) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            json_resp = response.json()
            result_id = json_resp.get("id")
            if not result_id:
                return {"error": "Media ID not found in response", "response": json_resp}
            return result_id
    except httpx.HTTPError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


async def _send_text(recipient: str, text: str, config: WhatsAppConfig, preview_url: bool = False) -> None:
    url = config.messages_url()
    headers = config.auth_headers()
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": preview_url, "body": text},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log_error(f"Failed to send WhatsApp text message: {e}")
        log_error(f"Error response: {e.response.text}")
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp text message: {str(e)}")
        raise


async def _send_media(
    media_type: str,
    media_id: str,
    recipient: str,
    config: WhatsAppConfig,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> None:
    url = config.messages_url()
    headers = config.auth_headers()
    media_payload: dict = {"id": media_id}
    if caption:
        media_payload["caption"] = caption
    if filename and media_type == "document":
        media_payload["filename"] = filename
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": media_type,
        media_type: media_payload,
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log_error(f"Failed to send WhatsApp {media_type} message: {e}")
        log_error(f"Error response: {e.response.text}")
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp {media_type} message: {str(e)}")
        raise


async def typing_indicator_async(message_id: Optional[str], config: WhatsAppConfig) -> Optional[dict]:
    if not message_id:
        return None
    url = config.messages_url()
    headers = config.auth_headers()
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
    except Exception as e:
        return {"error": str(e)}
    return None


def format_message(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text


async def send_whatsapp_message_async(
    recipient: str, message: Any, config: WhatsAppConfig, italics: bool = False
) -> None:
    if message is not None and not isinstance(message, str):
        from pydantic import BaseModel
        message = message.model_dump_json(indent=2) if isinstance(message, BaseModel) else str(message)
    if not message or not message.strip():
        return

    message = format_message(message)

    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    if len(message) <= 4096:
        await _send_text(recipient=recipient, text=_format(message), config=config)
        return

    message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await _send_text(recipient=recipient, text=_format(batch_message), config=config)


async def upload_and_send_media_async(
    media_items: list,
    media_type: str,
    recipient: str,
    config: WhatsAppConfig,
    response_content: Optional[str] = None,
    send_text_fallback: bool = True,
) -> bool:
    any_sent = False
    for item in media_items:
        raw_bytes = await item.aget_content_bytes()
        if not raw_bytes:
            log_warning(f"Could not process {media_type} content for user {recipient}.")
            if send_text_fallback:
                await send_whatsapp_message_async(recipient, response_content or "", config)
            continue

        if media_type == "image":
            detected = get_image_type(raw_bytes)
            if detected in ("jpeg", "png"):
                fmt = detected
            else:
                log_warning(f"Unsupported image format '{detected}' for WhatsApp, skipping upload")
                if send_text_fallback and response_content:
                    await _send_text(recipient=recipient, text=response_content, config=config)
                continue
            mime_type = f"image/{fmt}"
            filename = f"image.{fmt}"
        elif media_type == "document":
            filename = getattr(item, "name", None) or getattr(item, "filename", None) or "document"
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        elif media_type == "video":
            mime_type = getattr(item, "mime_type", None) or "video/mp4"
            filename = f"video.{mime_type.split('/')[-1]}"
        elif media_type == "audio":
            mime_type = getattr(item, "mime_type", None) or "audio/mpeg"
            if mime_type.split(";")[0] in _WHATSAPP_AUDIO_MIMES:
                fmt = getattr(item, "format", None) or mime_type.split("/")[-1]
                filename = f"audio.{fmt}"
            else:
                raw_bytes = pcm_to_wav_bytes(raw_bytes, channels=getattr(item, "channels", 1), rate=getattr(item, "sample_rate", 24000))
                mime_type, filename = "audio/wav", "audio.wav"
        else:
            mime_type, filename = "application/octet-stream", media_type

        mid = await upload_media_async(media_data=raw_bytes, mime_type=mime_type, filename=filename, config=config)
        if isinstance(mid, dict):
            log_warning(f"{media_type.title()} upload failed for user {recipient}: {mid}")
            if send_text_fallback:
                await send_whatsapp_message_async(recipient, response_content or "", config)
            continue

        caption = None
        if not any_sent and media_type in ("image", "video", "document") and response_content:
            caption = response_content[:1021] + "..." if len(response_content) > 1024 else response_content
        await _send_media(
            media_type=media_type,
            media_id=mid,
            recipient=recipient,
            config=config,
            caption=caption,
            filename=filename if media_type == "document" else None,
        )
        any_sent = True
    return any_sent
