"""Speech-to-text transcription service using Google Gemini.

Mirrors the structure of api/services/audio/tts.py. Reuses the same
google-genai client and GOOGLE_API_KEY env var, so no new dependencies are
required and no extra configuration is needed.

Usage:
    from api.services.audio.stt import transcribe_audio
    text = transcribe_audio(audio_bytes, mime_type="audio/ogg")
"""
import logging
import os

from google import genai
from google.genai import types

log = logging.getLogger("pasto-legal.services.stt")


def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    model: str | None = None,
) -> str | None:
    """Transcribe audio bytes into Portuguese-Brazilian text using Gemini.

    Args:
        audio_bytes: Raw audio content (any format Gemini accepts: ogg, wav,
            mp3, aac, amr, mpeg, ...).
        mime_type: MIME type of ``audio_bytes`` (e.g. ``"audio/ogg"``).
        model: Gemini model ID to use for transcription. Defaults to the
            ``STT_MODEL`` env var, falling back to ``gemini-2.5-flash``.

    Returns:
        The transcribed text, stripped of surrounding whitespace, or
        ``None`` if transcription failed or produced empty output.
    """
    if not audio_bytes:
        return None

    model_id = model or os.getenv("STT_MODEL", "gemini-3.5-flash-lite")

    try:
        client = genai.Client()
        log.debug(
            f"Transcribing audio  bytes={len(audio_bytes)}  mime={mime_type}  model={model_id}"
        )

        response = client.models.generate_content(
            model=model_id,
            contents=[
                types.Part(
                    inline_data=types.Blob(
                        data=audio_bytes,
                        mime_type=mime_type,
                    )
                ),
                (
                    "Transcreva este áudio em português brasileiro de forma fiel e literal. "
                    "Retorne apenas o texto transcrito, sem comentários ou aspas."
                ),
            ],
        )

        text = (response.text or "").strip()
        if not text:
            log.warning("STT returned empty text")
            return None

        log.debug(f"STT ok  text_len={len(text)}  text={text[:120]!r}")
        return text

    except Exception as e:
        log.error(f"STT failed: {e}")
        return None