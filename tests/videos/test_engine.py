import shutil
import subprocess

import pytest

from videos import render as cli
from videos.engine import (
    BUBBLE_MAX_W,
    CROSSFADE,
    Chat,
    FeatureList,
    TextCard,
    bubble,
    font,
    render,
    wrap,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg não instalado")


def _probe(path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_wrap_keeps_lines_within_width():
    lines = wrap("Para analisar a sua fazenda, preciso primeiro cadastrar a propriedade", 28, BUBBLE_MAX_W)
    assert len(lines) > 1
    assert all(font(28).getlength(line) <= BUBBLE_MAX_W for line in lines)


def test_wrap_breaks_words_longer_than_the_line():
    lines = wrap("GO-0000000-A1B2C3D4E5F60718293A4B5C6D7E8F90", 28, BUBBLE_MAX_W - 44)
    assert len(lines) > 1
    assert "".join(lines) == "GO-0000000-A1B2C3D4E5F60718293A4B5C6D7E8F90"
    assert all(font(28).getlength(line) <= BUBBLE_MAX_W - 44 for line in lines)


def test_bubble_accepts_empty_text_and_map_without_caption():
    assert bubble("user", "").height > 0
    assert bubble("bot", "", "map").height > 300


def test_chat_schedules_replies_after_questions():
    chat = Chat([("user", "Oi"), ("bot", "Olá!")])
    user, bot = chat.items
    assert bot["arrive"] > user["arrive"]
    assert bot["typing_from"] < bot["arrive"]


def test_chat_gives_longer_messages_more_reading_time():
    assert Chat([("bot", "Oi")]).duration < Chat([("bot", "Oi " * 30)]).duration


def test_feature_list_rejects_more_items_than_fit_on_screen():
    with pytest.raises(ValueError):
        FeatureList("Título", [("a", "b")] * 5)


@needs_ffmpeg
def test_render_produces_whatsapp_friendly_h264(tmp_path):
    output = render([TextCard([("Pasto Legal", 56, (27, 138, 72))], 1.0), Chat([("user", "Oi"), ("bot", "Olá!")], tail=0.5)], tmp_path / "out.mp4")

    assert _probe(output, "stream=codec_name,profile,width,height,pix_fmt,has_b_frames,color_space") == "h264,Main,720,1280,0,yuv420p,bt709"


def test_first_frame_already_shows_the_logo(tmp_path):
    scene = TextCard([("Pasto Legal", 56, (27, 138, 72))], 1.0)
    colors = scene.frame(0).convert("RGB").getcolors(1 << 20)
    assert len(colors) > 50


def test_render_rejects_empty_scene_list_and_scenes_shorter_than_the_transition(tmp_path):
    with pytest.raises(ValueError):
        render([], tmp_path / "out.mp4")
    with pytest.raises(ValueError):
        render([TextCard([("a", 40, (0, 0, 0))], CROSSFADE)], tmp_path / "out.mp4")


def test_render_reports_missing_ffmpeg_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg não encontrado"):
        render([TextCard([("a", 40, (0, 0, 0))], 1.0)], tmp_path / "out.mp4")


@needs_ffmpeg
def test_render_removes_the_partial_file_when_ffmpeg_fails(tmp_path):
    output = tmp_path / "out.invalid_ext"
    with pytest.raises(RuntimeError, match="ffmpeg falhou"):
        render([TextCard([("a", 40, (0, 0, 0))], 1.0)], output)
    assert not output.exists()


def test_cli_rejects_unknown_video_before_rendering(capsys):
    with pytest.raises(SystemExit):
        cli.main(["cadastro", "inexistente"])
    assert "inexistente" in capsys.readouterr().err
