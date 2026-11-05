import os
import random
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"
LOGO_PATH = ROOT / "assets" / "logos" / "pasto_legal_logo.png"

WIDTH, HEIGHT, FPS = 720, 1280, 30
CROSSFADE = 0.4
FADE_OUT = 0.5
FADE_STRENGTH = 0.6

GREEN = (27, 138, 72)
LIME = (177, 198, 35)
YELLOW = (241, 212, 58)
WHITE = (255, 255, 255)
CHAT_BG = (233, 228, 207)
INK = (31, 42, 31)
MUTED = (90, 105, 90)
USER_BUBBLE = (219, 232, 160)
BUBBLE_EDGE = (196, 200, 180)

HEADER_H = 130
INPUT_H = 110
CHAT_TOP = HEADER_H + 24
BUBBLE_GAP = 18
BUBBLE_MAX_W = 520
PAD = 22
LINE_H = 38
MAP_H = 240
SCROLL_SECONDS = 0.3
TYPING_SECONDS = 1.3
WORDS_PER_SECOND = 3.0
DWELL_SECONDS = 0.6


@cache
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


@cache
def logo(size: int) -> Image.Image:
    """Logo da marca com o fundo branco externo transparente."""
    img = Image.open(LOGO_PATH).convert("RGBA")
    ImageDraw.floodfill(img, (0, 0), (255, 255, 255, 0), thresh=24)
    return img.resize((size, size), Image.LANCZOS)


@cache
def avatar() -> Image.Image:
    """Círculo branco com a logo, desenhado em 4x para ter borda suavizada."""
    scale, size = 4, 84
    disc = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=WHITE)
    disc.alpha_composite(logo(70 * scale), (7 * scale, 7 * scale))
    return disc.resize((size, size), Image.LANCZOS)


def ease(x: float) -> float:
    """Suaviza uma progressão linear [0, 1] (ease-out cúbico)."""
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def reading_seconds(text: str) -> float:
    """Tempo de leitura confortável do texto (palavras por segundo da marca)."""
    return len(text.split()) / WORDS_PER_SECOND


def _fit(word: str, f: ImageFont.FreeTypeFont, max_width: int) -> int:
    """Maior prefixo de `word` que cabe em max_width, preferindo cortar logo após um hífen."""
    narrowest = min(f.getlength(c) for c in ".il'!") or 1
    low, high = 1, min(len(word), int(max_width / narrowest) + 1)
    while low < high:
        mid = (low + high + 1) // 2
        if f.getlength(word[:mid]) <= max_width:
            low = mid
        else:
            high = mid - 1
    hyphen = word.rfind("-", 0, low) + 1
    return hyphen if hyphen > 1 else low


def wrap(text: str, size: int, max_width: int) -> list[str]:
    """Quebra o texto em linhas que cabem em max_width pixels; palavras maiores que a linha são partidas."""
    f = font(size)
    lines, current = [], ""
    for word in text.split():
        while len(word) > 1 and (len(word) > int(max_width / 3) or f.getlength(word) > max_width):
            if current:
                lines.append(current)
                current = ""
            cut = _fit(word, f, max_width)
            lines.append(word[:cut])
            word = word[cut:]
        candidate = f"{current} {word}".strip()
        if f.getlength(candidate) <= max_width:
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


def _noise(rng: np.random.Generator, width: int, height: int, cells: int) -> np.ndarray:
    grid = (rng.random((cells + 1, cells + 1)) * 255).astype("uint8")
    return np.asarray(Image.fromarray(grid).resize((width, height), Image.BICUBIC), dtype=float) / 255


def fake_map(width: int, height: int) -> Image.Image:
    """Imagem de satélite ilustrativa (mata, pastos, estrada e açude sintéticos) com o contorno do imóvel."""
    rng = np.random.default_rng(11)
    relief = 0.5 * _noise(rng, width, height, 3) + 0.3 * _noise(rng, width, height, 7) + 0.2 * _noise(rng, width, height, 15)
    tone = _noise(rng, width, height, 5)[..., None]
    grain = (rng.random((height, width, 1)) - 0.5) * 22
    forest = np.array([38, 82, 46]) + grain
    pasture = np.array([148, 172, 82]) * (1 - tone) + np.array([196, 186, 108]) * tone + grain
    rgb = np.where((relief < 0.44)[..., None], forest, pasture)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.2)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = width, height
    draw.line([(0, h * .72), (w * .3, h * .62), (w * .62, h * .70), (w, h * .52)], fill=(205, 184, 140, 255), width=6, joint="curve")
    draw.ellipse((w * .70, h * .16, w * .80, h * .24), fill=(54, 96, 112, 255))
    for fence in ([(w * .30, h * .30), (w * .52, h * .78)], [(w * .52, h * .20), (w * .60, h * .80)]):
        draw.line(fence, fill=(214, 206, 160, 255), width=2)
    jitter = random.Random(5)
    polygon = [(w * x + jitter.uniform(-6, 6), h * y + jitter.uniform(-6, 6)) for x, y in
               [(.16, .34), (.30, .16), (.52, .10), (.72, .18), (.86, .36), (.80, .58), (.84, .78), (.58, .88), (.34, .84), (.14, .66)]]
    draw.line(polygon + [polygon[0]], fill=(229, 57, 53, 255), width=6, joint="curve")
    return img


def bubble(sender: str, text: str = "", kind: str = "text") -> Image.Image:
    """Renderiza um balão de conversa (texto, ou imagem do imóvel com legenda opcional) como RGBA."""
    if sender not in ("user", "bot") or kind not in ("text", "map"):
        raise ValueError(f"Balão inválido: sender={sender!r}, kind={kind!r}")
    color = USER_BUBBLE if sender == "user" else WHITE
    lines = wrap(text, 28, BUBBLE_MAX_W - 2 * PAD)
    image_h = MAP_H if kind == "map" else 0
    text_w = max((int(font(28).getlength(line)) for line in lines), default=0)
    width = BUBBLE_MAX_W if kind == "map" else max(text_w, 40) + 2 * PAD
    gap = 12 if image_h and lines else 0
    height = PAD * 2 + image_h + gap + LINE_H * len(lines)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=26, fill=color, outline=BUBBLE_EDGE, width=2)
    y = PAD
    if kind == "map":
        tile = fake_map(width - 2 * PAD, image_h)
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=16, fill=255)
        img.paste(tile, (PAD, y), mask)
        y += image_h + gap
    for line in lines:
        draw.text((PAD, y - 2), line, font=font(28), fill=INK)
        y += LINE_H
    return img


def typing_bubble(t: float) -> Image.Image:
    """Balão do assistente com três pontos pulsando (indicador de digitação)."""
    img = Image.new("RGBA", (120, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, 119, 63), radius=26, fill=WHITE, outline=BUBBLE_EDGE, width=2)
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
    """
    Cartão de texto sobre fundo colorido; a logo aparece desde o primeiro quadro e cada
    linha entra com fade e deslize, em sequência. Sem `duration`, o tempo vem do volume de texto.
    """

    def __init__(self, lines: list[tuple[str, int, tuple]], duration: float | None = None, background: tuple = WHITE, show_logo: bool = True):
        words = " ".join(text for text, _, _ in lines)
        super().__init__(duration or max(3.5, 2.0 + reading_seconds(words)))
        self.lines, self.background, self.show_logo = lines, background, show_logo
        self.blocks = [(wrap(text, size, WIDTH - 120), size, color) for text, size, color in lines]
        self.total = sum(len(wrapped) * int(size * 1.35) + 24 for wrapped, size, _ in self.blocks)
        if self.total + (300 if show_logo else 0) > HEIGHT - 200:
            raise ValueError("Texto demais para um cartão: reduza as linhas ou o tamanho da fonte")

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), self.background + (255,))
        blocks, total = self.blocks, self.total
        logo_h = 300 if self.show_logo else 0
        y = (HEIGHT - total - logo_h) // 2
        if self.show_logo:
            paste_center(canvas, logo(300), WIDTH // 2, y)
            y += logo_h + 10
        for i, (wrapped, size, color) in enumerate(blocks):
            progress = ease((t - 0.3 - i * 0.35) / 0.5)
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
    """Título seguido de cartões de funcionalidade que entram um a um, cada qual com tempo de leitura proporcional ao texto."""

    CARD_H = 190
    MAX_ITEMS = 4

    def __init__(self, title: str, items: list[tuple[str, str]]):
        if len(items) > self.MAX_ITEMS:
            raise ValueError(f"FeatureList comporta no máximo {self.MAX_ITEMS} itens na tela")
        self.title, self.items, self.starts, clock = title, items, [], 0.6
        for head, sub in items:
            self.starts.append(clock)
            clock += 1.2 + 0.6 * reading_seconds(f"{head} {sub}")
        super().__init__(clock + 1.5)

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), WHITE + (255,))
        draw = ImageDraw.Draw(canvas)
        y = 170
        for line in wrap(self.title, 52, WIDTH - 100):
            draw.text((50, y), line, font=font(52), fill=GREEN)
            y += 66
        y += 40
        palette = [GREEN, LIME, YELLOW, GREEN]
        for i, (head, sub) in enumerate(self.items):
            progress = ease((t - self.starts[i]) / 0.5)
            card = Image.new("RGBA", (WIDTH - 100, self.CARD_H), (0, 0, 0, 0))
            cd = ImageDraw.Draw(card)
            cd.rounded_rectangle((0, 0, card.width - 1, self.CARD_H - 1), radius=30, fill=(244, 246, 236), outline=BUBBLE_EDGE, width=2)
            cd.rounded_rectangle((0, 0, 26, self.CARD_H - 1), radius=13, fill=palette[i])
            cd.text((56, 30), head, font=font(36), fill=INK)
            for j, line in enumerate(wrap(sub, 26, card.width - 90)):
                cd.text((56, 88 + j * 34), line, font=font(26), fill=MUTED)
            canvas.alpha_composite(with_alpha(card, progress), (50, int(y + (1 - progress) * 40)))
            y += self.CARD_H + 25
        return canvas


class Chat(Scene):
    """Conversa animada no estilo WhatsApp: balões entram em sequência, com indicador de digitação nas respostas."""

    def __init__(self, messages: list[tuple], lead_in: float = 0.8, tail: float = 2.0):
        self.items, clock, y = [], lead_in, CHAT_TOP
        for message in messages:
            sender, text, kind = (message + ("text",))[:3]
            img = bubble(sender, text, kind)
            typing = TYPING_SECONDS if sender == "bot" else 0.0
            arrive = clock + typing
            self.items.append({"sender": sender, "img": img, "y": y, "arrive": arrive, "typing_from": clock})
            clock = arrive + DWELL_SECONDS + reading_seconds(text)
            y += img.height + BUBBLE_GAP
        self.viewport = HEIGHT - INPUT_H - CHAT_TOP
        super().__init__(clock + tail - DWELL_SECONDS)

    def scroll(self, t: float) -> float:
        offset, previous = 0.0, 0.0
        for item in self.items:
            target = max(0.0, item["y"] + item["img"].height - CHAT_TOP - self.viewport + 24)
            if t >= item["typing_from"]:
                offset = previous + (target - previous) * ease((t - item["typing_from"]) / SCROLL_SECONDS)
            previous = target
        return offset

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), CHAT_BG + (255,))
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
        canvas.alpha_composite(avatar(), (24, 23))
        draw.text((128, 36), "Pasto Legal", font=font(34), fill=WHITE)
        draw.text((128, 80), "online", font=font(22), fill=(245, 252, 247))
        draw.rectangle((0, HEIGHT - INPUT_H, WIDTH, HEIGHT), fill=(224, 220, 198))
        draw.rounded_rectangle((28, HEIGHT - INPUT_H + 22, WIDTH - 28, HEIGHT - 22), radius=33, fill=WHITE)
        draw.text((58, HEIGHT - INPUT_H + 38), "Mensagem", font=font(26), fill=(120, 130, 120))
        return canvas


def frame_at(scenes: list[Scene], starts: list[float], t: float) -> Image.Image:
    active = [(s, t - st) for s, st in zip(scenes, starts, strict=True) if st <= t < st + s.duration]
    if len(active) == 1:
        scene, local = active[0]
        return scene.frame(local)
    (first, t1), (second, t2) = active[0], active[1]
    return Image.blend(first.frame(t1), second.frame(t2), ease(t2 / CROSSFADE))


def render(scenes: list[Scene], output: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    """
    Renderiza as cenas, com transição suave entre elas e fade final, em MP4 (H.264 Main sem
    B-frames, yuv420p, bt709, faststart), no perfil recomendado pela Meta para o WhatsApp.

    Args:
        scenes (list[Scene]): Cenas na ordem de exibição; cada uma deve durar ao menos 2x o CROSSFADE.
        output (Path): Caminho do MP4 de saída.
        progress (Callable | None): Callback (quadro atual, total de quadros).

    Returns:
        Path: Caminho do MP4 gerado.

    Raises:
        ValueError: Quando não há cenas ou alguma cena é curta demais para a transição.
        RuntimeError: Quando o ffmpeg não é encontrado ou falha na codificação. O MP4 é gravado em arquivo parcial
            e só substitui o destino ao terminar, então uma falha ou interrupção nunca deixa vídeo truncado.
    """
    output = Path(output)
    if not scenes:
        raise ValueError("Nenhuma cena para renderizar")
    for scene in scenes:
        if scene.duration < 2 * CROSSFADE:
            raise ValueError(f"Cena com {scene.duration:.2f} s: a duração mínima é {2 * CROSSFADE:.1f} s")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg não encontrado no PATH: instale o ffmpeg com libx264")

    starts = [0.0]
    for scene in scenes[:-1]:
        starts.append(starts[-1] + scene.duration - CROSSFADE)
    total_seconds = starts[-1] + scenes[-1].duration
    total = int(total_seconds * FPS)

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.{os.getpid()}.part")
    command = [
        ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-c:v", "libx264", "-profile:v", "main", "-bf", "0", "-crf", "20",
        "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
        "-movflags", "+faststart", "-an", "-f", "mp4", str(partial),
    ]
    white = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    with tempfile.TemporaryFile() as stderr:
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=stderr)
        try:
            for n in range(total):
                t = min(n / FPS, total_seconds - 1e-3)
                frame = frame_at(scenes, starts, t).convert("RGB")
                fade = (t - (total_seconds - FADE_OUT)) / FADE_OUT
                if fade > 0:
                    frame = Image.blend(frame, white, FADE_STRENGTH * min(fade, 1.0))
                encoder.stdin.write(frame.tobytes())
                if progress:
                    progress(n + 1, total)
        except BrokenPipeError:
            pass
        except BaseException:
            encoder.kill()
            encoder.wait()
            partial.unlink(missing_ok=True)
            raise
        finally:
            with suppress(BrokenPipeError):
                encoder.stdin.close()
        returncode = encoder.wait()
        if returncode != 0:
            stderr.seek(0)
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg falhou ({returncode}): {stderr.read().decode(errors='replace')}")
    os.replace(partial, output)
    return output
