"""Unit tests for api/services/audio/stt.py.

Mocks the google.genai client so tests run without network or API key.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import api.services.audio.stt as stt_mod


class _FakeBlob:
    def __init__(self, data, mime_type):
        self.data = data
        self.mime_type = mime_type


class _FakePart:
    def __init__(self, inline_data=None, text=None):
        if inline_data is not None:
            self.inline_data = inline_data
        if text is not None:
            self.text = text


class _FakeTypes:
    Part = _FakePart
    Blob = _FakeBlob


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _build_fake_client(transcript: str):
    """Return a MagicMock whose .models.generate_content returns ``transcript``."""
    fake = MagicMock()
    fake.models.generate_content.return_value = _FakeResponse(transcript)
    return fake


@contextmanager
def patched_genai(transcript: str = "", side_effect=None):
    """Patch stt_mod.genai and stt_mod.types with fakes."""
    fake_client = MagicMock()
    if side_effect is not None:
        fake_client.models.generate_content.side_effect = side_effect
    else:
        fake_client.models.generate_content.return_value = _FakeResponse(transcript)
    with patch.object(stt_mod, "genai") as fake_genai, patch.object(stt_mod, "types", _FakeTypes):
        fake_genai.Client.return_value = fake_client
        yield fake_client


def test_transcribe_audio_returns_text():
    with patched_genai(transcript="Bom dia, quero ver meu pasto") as fake_client:
        result = stt_mod.transcribe_audio(b"\x00\x01\x02", mime_type="audio/ogg")

    assert result == "Bom dia, quero ver meu pasto"
    call_args = fake_client.models.generate_content.call_args
    contents = call_args.kwargs.get("contents")
    assert contents is not None
    assert any(
        isinstance(c, _FakePart) and c.inline_data.mime_type == "audio/ogg"
        for c in contents
    )


def test_transcribe_audio_empty_bytes_returns_none():
    assert stt_mod.transcribe_audio(b"", mime_type="audio/ogg") is None


def test_transcribe_audio_strips_whitespace():
    with patched_genai(transcript="  olá  \n"):
        result = stt_mod.transcribe_audio(b"\x01", mime_type="audio/wav")
    assert result == "olá"


def test_transcribe_audio_empty_response_returns_none():
    with patched_genai(transcript=""):
        result = stt_mod.transcribe_audio(b"\x01", mime_type="audio/wav")
    assert result is None


def test_transcribe_audio_exception_returns_none():
    with patched_genai(side_effect=RuntimeError("api down")):
        result = stt_mod.transcribe_audio(b"\x01", mime_type="audio/wav")
    assert result is None


def test_transcribe_audio_default_model(monkeypatch):
    monkeypatch.delenv("STT_MODEL", raising=False)
    with patched_genai(transcript="oi") as fake_client:
        stt_mod.transcribe_audio(b"\x01", mime_type="audio/ogg")
    call_args = fake_client.models.generate_content.call_args
    assert call_args.kwargs.get("model") == "gemini-flash-latest"


def test_transcribe_audio_uses_env_model(monkeypatch):
    monkeypatch.setenv("STT_MODEL", "gemini-test-model")
    with patched_genai(transcript="oi") as fake_client:
        stt_mod.transcribe_audio(b"\x01", mime_type="audio/ogg")
    call_args = fake_client.models.generate_content.call_args
    assert call_args.kwargs.get("model") == "gemini-test-model"