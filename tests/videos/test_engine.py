import subprocess

from videos.engine import BUBBLE_MAX_W, Chat, TextCard, font, render, wrap


def test_wrap_keeps_lines_within_width():
    lines = wrap("Para analisar a sua fazenda, preciso primeiro cadastrar a propriedade", 28, BUBBLE_MAX_W)
    assert len(lines) > 1
    assert all(font(28).getlength(line) <= BUBBLE_MAX_W for line in lines)


def test_chat_schedules_replies_after_questions():
    chat = Chat([("user", "Oi"), ("bot", "Olá!")])
    user, bot = chat.items
    assert bot["arrive"] > user["arrive"]
    assert bot["typing_from"] < bot["arrive"]


def test_render_produces_h264_mp4(tmp_path):
    output = render([TextCard([("Pasto Legal", 56, (27, 138, 72))], 1.0), Chat([("user", "Oi"), ("bot", "Olá!")], tail=0.5)], tmp_path / "out.mp4")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,pix_fmt", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert probe == "h264,720,1280,yuv420p"
