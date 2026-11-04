import random
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"
LOGO_PATH = ROOT / "assets" / "logos" / "pasto_legal_logo.png"

WIDTH, HEIGHT, FPS = 720, 1280, 30
CROSSFADE = 0.4

GREEN = (27, 138, 72)
LIME = (177, 198, 35)
YELLOW = (241, 212, 58)
CREAM = (247, 245, 232)
INK = (31, 42, 31)
WHITE = (255, 255, 255)
USER_BUBBLE = (226, 238, 176)

HEADER_H = 130
INPUT_H = 110
BUBBLE_GAP = 18
BUBBLE_MAX_W = 520
PAD = 22


@lru_cache(maxsize=None)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


@lru_cache(maxsize=None)
def logo(size: int) -> Image.Image:
    return Image.open(LOGO_PATH).convert("RGBA").resize((size, size), Image.LANCZOS)


def ease(x: float) -> float:
    """Suaviza uma progressão linear [0, 1] (ease-out cúbico)."""
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def wrap(text: str, size: int, max_width: int) -> list[str]:
    """Quebra o texto em linhas que cabem em max_width pixels na fonte da marca."""
    f = font(size)
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if f.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    return lines + [current] if current else lines


def with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    return img


def paste_center(canvas: Image.Image, img: Image.Image, cx: int, y: int) -> None:
    canvas.alpha_composite(img, (cx - img.width // 2, y))


def fake_map(width: int, height: int) -> Image.Image:
    """Imagem de satélite ilustrativa (terreno sintético) com o contorno do imóvel."""
    rng = random.Random(7)
    img = Image.new("RGBA", (width, height), (96, 128, 62, 255))
    draw = ImageDraw.Draw(img)
    for _ in range(260):
        x, y, r = rng.randint(0, width), rng.randint(0, height), rng.randint(8, 42)
        tone = rng.choice([(78, 112, 52), (120, 150, 76), (140, 120, 80), (66, 98, 48)])
        draw.ellipse((x - r, y - r, x + r, y + r), fill=tone + (255,))
    img = img.filter(ImageFilter.GaussianBlur(3))
    draw = ImageDraw.Draw(img)
    w, h = width, height
    polygon = [(w * .18, h * .30), (w * .50, h * .12), (w * .84, h * .34), (w * .74, h * .80), (w * .34, h * .88), (w * .12, h * .62)]
    draw.line(polygon + [polygon[0]], fill=(229, 57, 53, 255), width=7, joint="curve")
    return img


def bubble(sender: str, text: str = "", kind: str = "text") -> Image.Image:
    """Renderiza um balão de conversa (texto, ou imagem do imóvel com legenda) como RGBA."""
    color = USER_BUBBLE if sender == "user" else WHITE
    lines = wrap(text, 28, BUBBLE_MAX_W - 2 * PAD) if text else []
    line_h = 38
    image_h = 300 if kind == "map" else 0
    width = BUBBLE_MAX_W if kind == "map" else int(max(font(28).getlength(l) for l in lines)) + 2 * PAD
    height = PAD * 2 + image_h + (image_h and lines and 12) + line_h * len(lines)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=26, fill=color)
    y = PAD
    if kind == "map":
        tile = fake_map(width - 2 * PAD, image_h)
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=16, fill=255)
        img.paste(tile, (PAD, y), mask)
        y += image_h + 12
    for line in lines:
        draw.text((PAD, y - 2), line, font=font(28), fill=INK)
        y += line_h
    return img


def typing_bubble(t: float) -> Image.Image:
    """Balão do assistente com três pontos pulsando (indicador de digitação)."""
    img = Image.new("RGBA", (120, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, 119, 63), radius=26, fill=WHITE)
    for i in range(3):
        lift = abs(((t * 3 + i * 0.33) % 1) - 0.5) * 12
        draw.ellipse((28 + i * 24, 26 - lift, 42 + i * 24, 40 - lift), fill=(150, 160, 150, 255))
    return img


class Scene:
    """Cena com duração fixa; `frame(t)` devolve o quadro RGBA no instante t (segundos)."""

    def __init__(self, duration: float):
        self.duration = duration

    def frame(self, t: float) -> Image.Image:
        raise NotImplementedError


class TextCard(Scene):
    """Cartão de texto sobre fundo colorido; cada linha entra com fade e deslize, em sequência."""

    def __init__(self, lines: list[tuple[str, int, tuple]], duration: float = 3.0, background: tuple = WHITE, show_logo: bool = True):
        super().__init__(duration)
        self.lines, self.background, self.show_logo = lines, background, show_logo

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), self.background + (255,))
        blocks = [(wrap(text, size, WIDTH - 120), size, color) for text, size, color in self.lines]
        total = sum(len(wrapped) * int(size * 1.35) + 24 for wrapped, size, _ in blocks)
        logo_h = 300 if self.show_logo else 0
        y = (HEIGHT - total - logo_h) // 2
        if self.show_logo:
            progress = ease(t / 0.6)
            paste_center(canvas, with_alpha(logo(300), progress), WIDTH // 2, int(y + (1 - progress) * 30))
            y += logo_h + 10
        for i, (wrapped, size, color) in enumerate(blocks):
            progress = ease((t - 0.5 - i * 0.35) / 0.5)
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            ty = y + int((1 - progress) * 24)
            for line in wrapped:
                draw.text(((WIDTH - font(size).getlength(line)) / 2, ty), line, font=font(size), fill=color)
                ty += int(size * 1.35)
            canvas.alpha_composite(with_alpha(layer, progress))
            y += len(wrapped) * int(size * 1.35) + 24
        return canvas


class FeatureList(Scene):
    """Título seguido de cartões de funcionalidade que entram um a um."""

    def __init__(self, title: str, items: list[tuple[str, str]], duration: float = 7.0):
        super().__init__(duration)
        self.title, self.items = title, items

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), CREAM + (255,))
        draw = ImageDraw.Draw(canvas)
        y = 170
        for line in wrap(self.title, 52, WIDTH - 100):
            draw.text((50, y), line, font=font(52), fill=GREEN)
            y += 66
        y += 40
        palette = [GREEN, LIME, YELLOW, (27, 138, 72)]
        for i, (head, sub) in enumerate(self.items):
            progress = ease((t - 0.6 - i * 0.9) / 0.5)
            card = Image.new("RGBA", (WIDTH - 100, 190), (0, 0, 0, 0))
            cd = ImageDraw.Draw(card)
            cd.rounded_rectangle((0, 0, card.width - 1, 189), radius=30, fill=WHITE)
            cd.rounded_rectangle((0, 0, 26, 189), radius=13, fill=palette[i % len(palette)])
            cd.text((56, 30), head, font=font(36), fill=INK)
            for j, line in enumerate(wrap(sub, 26, card.width - 90)):
                cd.text((56, 88 + j * 34), line, font=font(26), fill=(90, 105, 90))
            canvas.alpha_composite(with_alpha(card, progress), (50, int(y + (1 - progress) * 40)))
            y += 215
        return canvas


class Chat(Scene):
    """Conversa animada no estilo WhatsApp: balões entram em sequência, com indicador de digitação nas respostas."""

    def __init__(self, messages: list[tuple], lead_in: float = 0.8, tail: float = 2.2):
        self.items, clock, y = [], lead_in, HEADER_H + 24
        for message in messages:
            sender, text, kind = (message + ("text",))[:3]
            img = bubble(sender, text, kind)
            typing = 1.3 if sender == "bot" else 0.0
            arrive = clock + typing
            self.items.append({"sender": sender, "img": img, "y": y, "arrive": arrive, "typing_from": clock})
            clock = arrive + 0.9 + 0.035 * len(text)
            y += img.height + BUBBLE_GAP
        self.viewport = HEIGHT - INPUT_H - (HEADER_H + 24)
        super().__init__(clock + tail - 0.9)

    def scroll(self, t: float) -> float:
        offset, previous = 0.0, 0.0
        for item in self.items:
            target = max(0.0, item["y"] + item["img"].height - (HEADER_H + 24) - self.viewport + 10)
            start = item["typing_from"]
            if t >= start:
                offset = previous + (target - previous) * ease((t - start) / 0.4)
            previous = target
        return offset

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), CREAM + (255,))
        offset = self.scroll(t)
        for item in self.items:
            x = WIDTH - 36 - item["img"].width if item["sender"] == "user" else 36
            y = int(item["y"] - offset)
            if item["typing_from"] <= t < item["arrive"] and item["sender"] == "bot":
                canvas.alpha_composite(typing_bubble(t), (x, y))
            elif t >= item["arrive"]:
                progress = ease((t - item["arrive"]) / 0.3)
                canvas.alpha_composite(with_alpha(item["img"], progress), (x, y + int((1 - progress) * 20)))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, WIDTH, HEADER_H), fill=GREEN)
        draw.ellipse((28, 30, 98, 100), fill=WHITE)
        canvas.alpha_composite(logo(60), (33, 35))
        draw.text((118, 36), "Pasto Legal", font=font(34), fill=WHITE)
        draw.text((118, 80), "online", font=font(22), fill=(200, 230, 210))
        draw.rectangle((0, HEIGHT - INPUT_H, WIDTH, HEIGHT), fill=(236, 233, 218))
        draw.rounded_rectangle((28, HEIGHT - INPUT_H + 22, WIDTH - 28, HEIGHT - 22), radius=33, fill=WHITE)
        draw.text((58, HEIGHT - INPUT_H + 38), "Mensagem", font=font(26), fill=(150, 160, 150))
        return canvas


def frame_at(scenes: list[Scene], starts: list[float], t: float) -> Image.Image:
    active = [(s, t - st) for s, st in zip(scenes, starts) if st <= t < st + s.duration]
    if len(active) == 1:
        scene, local = active[0]
        return scene.frame(local)
    (first, t1), (second, t2) = active[0], active[1]
    return Image.blend(first.frame(t1), second.frame(t2), ease(t2 / CROSSFADE))


def render(scenes: list[Scene], output: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    """
    Renderiza as cenas, com transição suave entre elas, em MP4 (H.264, yuv420p, faststart).

    Args:
        scenes (list[Scene]): Cenas na ordem de exibição.
        output (Path): Caminho do MP4 de saída.
        progress (Callable | None): Callback (quadro atual, total de quadros).

    Returns:
        Path: Caminho do MP4 gerado.

    Raises:
        RuntimeError: Quando o ffmpeg falha na codificação.
    """
    starts = [0.0]
    for scene in scenes[:-1]:
        starts.append(starts[-1] + scene.duration - CROSSFADE)
    total_seconds = starts[-1] + scenes[-1].duration
    total = int(total_seconds * FPS)

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "main",
        "-crf", "23", "-movflags", "+faststart", "-an", str(output),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for n in range(total):
        encoder.stdin.write(frame_at(scenes, starts, min(n / FPS, total_seconds - 1e-3)).convert("RGB").tobytes())
        if progress:
            progress(n + 1, total)
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError(f"ffmpeg falhou: {encoder.stderr.read().decode()}")
    return output
