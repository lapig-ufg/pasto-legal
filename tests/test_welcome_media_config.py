"""Os vídeos de boas-vindas configurados no semente.yaml existem e são MP4."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
VIDEOS = (yaml.safe_load((ROOT / "semente.yaml").read_text(encoding="utf-8"))["features"].get("welcome-media") or {}).get("videos", [])


def test_welcome_media_is_configured():
    assert VIDEOS


@pytest.mark.parametrize("video", VIDEOS)
def test_welcome_video_exists_and_is_an_mp4(video):
    content = (ROOT / video).read_bytes()

    assert content[4:8] == b"ftyp"
    assert len(content) < 16 * 1024 * 1024
