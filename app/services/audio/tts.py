import logging
import os
import uuid
import base64
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from google import genai

log = logging.getLogger("pasto-legal.services.tts")


@dataclass
class Audio:
    """Simple audio result container (replaces agno.media.Audio)."""
    filepath: Optional[str] = None
    mime_type: Optional[str] = None
    content: bytes = b""


def generate_speech(text: str, user_id: str = "default") -> Optional[Audio]:
    """
    Generates audio speech from the given text using Google's Gemini model.

    Args:
        text: The text to be converted into speech.
        user_id: User identifier for file organization.

    Returns:
        Audio object with filepath to the generated OGG file, or None on failure.
    """
    try:
        client = genai.Client()
        log.debug("Generating speech")
        log.debug(text)

        prompt = f"Diga de forma simples e direta, use o sotaque muito leve e girias do contexto agro: {text}"

        interaction = client.interactions.create(
            model="gemini-3.1-flash-tts-preview",
            input=prompt,
            response_format={"type": "audio"},
            generation_config={
                "speech_config": [
                    {"voice": "Kore"}
                ]
            }
        )

        if interaction.output_audio and interaction.output_audio.data:
            audio_bytes = base64.b64decode(interaction.output_audio.data)

            script_dir = Path(__file__).parent.parent.parent.parent
            storage_dir = script_dir / "tmp" / "audio" / user_id
            storage_dir.mkdir(parents=True, exist_ok=True)

            filename = f"speech{uuid.uuid4().hex[:8]}.wav"
            file_path = storage_dir / filename

            framerate = 24000
            with wave.open(str(file_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(framerate)
                wav_file.writeframes(audio_bytes)

            ffmpeg_env_path = os.getenv("FFMPEG_PATH")
            if ffmpeg_env_path:
                os.environ["PATH"] += os.pathsep + ffmpeg_env_path

            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_wav(str(file_path))
                ogg_path = file_path.with_suffix(".ogg")
                audio.export(str(ogg_path), format="ogg", codec="libopus")
                os.remove(file_path)
                file_path = ogg_path
                return Audio(filepath=str(file_path), mime_type="audio/ogg")
            except ImportError:
                log.error("pydub not installed.")
            except Exception as e:
                log.error(f"Audio conversion failed: {e}.")

    except Exception as e:
        log.error(f"Speech generation failed: {e}.")

    return None
