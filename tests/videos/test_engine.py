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
    assert bubble("bot", "", "map").height > 240


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


def test_render_leaves_no_file_behind_when_ffmpeg_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/false")
    output = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError, match="ffmpeg falhou"):
        render([TextCard([("a", 40, (0, 0, 0))], 1.0)], output)
    assert list(tmp_path.iterdir()) == []


@needs_ffmpeg
def test_render_keeps_the_previous_video_until_the_new_one_is_complete(tmp_path):
    output = tmp_path / "out.mp4"
    output.write_bytes(b"video anterior")

    def interrupt(n, total):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        render([TextCard([("a", 40, (0, 0, 0))], 1.0)], output, progress=interrupt)

    assert output.read_bytes() == b"video anterior"
    assert [p.name for p in tmp_path.iterdir()] == ["out.mp4"]


@needs_ffmpeg
def test_concurrent_renders_to_the_same_output_do_not_corrupt_it(tmp_path):
    output = tmp_path / "out.mp4"
    code = f"from pathlib import Path; from videos.engine import TextCard, render; render([TextCard([('a', 40, (0, 0, 0))], 1.0)], Path('{output}'))"
    procs = [subprocess.Popen(["uv", "run", "python", "-c", code]) for _ in range(2)]
    assert [p.wait() for p in procs] == [0, 0]
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"], check=True, capture_output=True)
    assert [p.name for p in tmp_path.iterdir()] == ["out.mp4"]


def test_cli_rejects_unknown_video_before_rendering(capsys):
    with pytest.raises(SystemExit):
        cli.main(["cadastro", "inexistente"])
    assert "inexistente" in capsys.readouterr().err


def test_wrap_handles_huge_unbroken_words_quickly():
    import time

    start = time.time()
    lines = wrap("A" * 20000, 28, BUBBLE_MAX_W)
    assert time.time() - start < 3
    assert "".join(lines) == "A" * 20000


def test_wrap_breaks_long_codes_after_the_hyphen():
    assert wrap("GO-0000000-A1B2C3D4E5F60718293A4B5C6D7E8F90", 28, BUBBLE_MAX_W - 44)[0] == "GO-0000000-"


def test_bubble_rejects_unknown_sender_or_kind():
    with pytest.raises(ValueError):
        bubble("robot", "Oi")
    with pytest.raises(ValueError):
        bubble("bot", "Oi", "video")


def test_text_card_rejects_text_that_does_not_fit_the_screen():
    with pytest.raises(ValueError):
        TextCard([("palavra " * 200, 40, (0, 0, 0))])
