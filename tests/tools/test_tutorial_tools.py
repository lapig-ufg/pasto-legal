"""
Envio dos vídeos tutoriais do Pasto Legal (assets/videos).

    uv run pytest tests/tools/test_tutorial_tools.py -v
"""
import pytest

from domain.agent import get_tools
from domain.tools import tutorial_tools
from domain.tools.tutorial_tools import (
    TUTORIAL_VIDEOS,
    TUTORIAL_VIDEOS_DIR,
    send_tutorial_video,
)


class _Context:
    def __init__(self, session_state):
        self.session_state = session_state


def _send(video: str):
    return send_tutorial_video.func(_Context({}), video=video)


@pytest.mark.parametrize("video", TUTORIAL_VIDEOS)
def test_every_tutorial_video_is_committed_and_sent_as_mp4(video):
    assert (TUTORIAL_VIDEOS_DIR / f"pasto_legal_{video}.mp4").is_file()

    result = _send(video)

    assert result.videos[0].mime_type == "video/mp4"
    assert result.videos[0].content[4:8] == b"ftyp"
    assert TUTORIAL_VIDEOS[video] in result.content


def test_unknown_video_lists_the_options_without_sending_anything():
    result = _send("../../etc/passwd")

    assert not result.videos
    assert "primeiras_interacoes" in result.content


def test_missing_file_is_reported_instead_of_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(tutorial_tools, "TUTORIAL_VIDEOS_DIR", tmp_path)

    result = _send("cadastro")

    assert not result.videos


def test_tool_is_available_in_the_default_state_only():
    default = {getattr(t, "name", None) for t in get_tools(_Context({}))}
    pending = {getattr(t, "name", None) for t in get_tools(_Context({"registration_state": "pending", "candidate_properties": []}))}

    assert "send_tutorial_video" in default
    assert "send_tutorial_video" not in pending
