"""
Testes do vídeo de biomassa acumulada (T2G).

Cobre a iteração de meses de referência (`_iterate_reference_months`), a conversão
GIF -> MP4 (`gif_bytes_to_mp4_bytes`) e um teste de integração opcional com o
Earth Engine que gera o vídeo real.

Os testes unitários não chamam o GEE, mas `app/services/geospatial/gee.py`
inicializa o Earth Engine na importação do módulo, então este arquivo precisa de
um `.env` real na raiz do projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE,
APP_ENV) — mesma ressalva de tests/ee_scripts/test_pasture_classification.py.

    PYTHONPATH=. uv run pytest tests/ee_scripts/test_biomass_video.py -v
"""
import datetime
import os
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image as PILImage
from PIL import ImageChops

from app.services.geospatial.gee import (
    BIOMASS_VIDEO_MIN_YEAR,
    _iterate_reference_months,
    retrieve_t2g_biomass_video,
)
from app.services.video import gif_bytes_to_mp4_bytes

def _ffmpeg_available() -> bool:
    if shutil.which("ffmpeg"):
        return True
    ffmpeg_path = os.getenv("FFMPEG_PATH")
    return bool(ffmpeg_path) and shutil.which("ffmpeg", path=ffmpeg_path) is not None

_FFMPEG_AVAILABLE = _ffmpeg_available()


# --- _iterate_reference_months: intervalo válido ---
def test_iterate_months_simple_range():
    months, start, end = _iterate_reference_months(2025, 1, 2025, 3)
    assert months == [(2025, 1), (2025, 2), (2025, 3)]
    assert (start, end) == ((2025, 1), (2025, 3))


def test_iterate_months_crosses_year_boundary():
    months, _, _ = _iterate_reference_months(2025, 11, 2026, 2)
    assert months == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


def test_iterate_months_single_month():
    months, start, end = _iterate_reference_months(2025, 6, 2025, 6)
    assert months == [(2025, 6)]
    assert (start, end) == ((2025, 6), (2025, 6))


def test_iterate_months_inclusive_end():
    months, _, _ = _iterate_reference_months(2025, 1, 2025, 12)
    assert len(months) == 12
    assert months[-1] == (2025, 12)


# --- _iterate_reference_months: limite de ano inicial ---
def test_iterate_months_rejects_start_before_min_year():
    with pytest.raises(ValueError, match=str(BIOMASS_VIDEO_MIN_YEAR)):
        _iterate_reference_months(2024, 6, 2025, 6)


def test_iterate_months_accepts_start_at_min_year():
    months, _, _ = _iterate_reference_months(BIOMASS_VIDEO_MIN_YEAR, 1, 2025, 1)
    assert months == [(2025, 1)]


# --- _iterate_reference_months: clamp do fim no mês atual ---
def test_iterate_months_clamps_end_to_current_month():
    today = datetime.date.today()
    months, start, end = _iterate_reference_months(2025, 1, today.year + 1, 5)

    assert end == (today.year, today.month)
    assert months[-1] == (today.year, today.month)
    assert start == (2025, 1)


def test_iterate_months_keeps_end_within_current_month():
    today = datetime.date.today()
    past_year = BIOMASS_VIDEO_MIN_YEAR if today.year > BIOMASS_VIDEO_MIN_YEAR else today.year
    _, _, end = _iterate_reference_months(past_year, 1, today.year, max(1, today.month - 1))
    assert end[0] == today.year or end[0] == past_year
    assert end[1] <= today.month


# --- _iterate_reference_months: erros ---
def test_iterate_months_rejects_invalid_month():
    with pytest.raises(ValueError, match=r"entre 1 \(janeiro\) e 12"):
        _iterate_reference_months(2025, 0, 2025, 6)
    with pytest.raises(ValueError, match=r"entre 1 \(janeiro\) e 12"):
        _iterate_reference_months(2025, 1, 2025, 13)


def test_iterate_months_rejects_start_after_end():
    with pytest.raises(ValueError, match="anterior ou igual"):
        _iterate_reference_months(2025, 6, 2025, 1)


def test_iterate_months_rejects_start_after_current_month():
    today = datetime.date.today()
    future_month = today.month + 1 if today.month < 12 else 12
    future_year = today.year if today.month < 12 else today.year + 1
    with pytest.raises(ValueError):
        _iterate_reference_months(future_year, future_month, future_year, future_month)


# --- gif_bytes_to_mp4_bytes ---
def _make_animated_gif(frames: int = 3, size: tuple = (64, 48)) -> bytes:
    images = []
    for i in range(frames):
        img = PILImage.new("RGB", size, color=(i * 40 % 255, 100, 200))
        images.append(img)
    buffer_path = Path(__file__).parent / "_tmp_test_frames.gif"
    images[0].save(buffer_path, save_all=True, append_images=images[1:], duration=500, loop=0)
    data = buffer_path.read_bytes()
    buffer_path.unlink()
    return data


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg não instalado no host")
def test_gif_to_mp4_raises_on_invalid_input():
    with pytest.raises(RuntimeError, match="ffmpeg"):
        gif_bytes_to_mp4_bytes(b"not-a-gif")


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg não instalado no host")
def test_gif_to_mp4_produces_valid_mp4():
    gif_bytes = _make_animated_gif()

    mp4_bytes = gif_bytes_to_mp4_bytes(gif_bytes)

    assert len(mp4_bytes) > 0
    # Assinatura ftyp box de MP4
    assert mp4_bytes[4:8] == b"ftyp"


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg não instalado no host")
def test_gif_to_mp4_raises_on_invalid_input():
    with pytest.raises(RuntimeError, match="ffmpeg"):
        gif_bytes_to_mp4_bytes(b"not-a-gif")


# --- _overlay_fixed_colorbar: rótulos de data por frame ---
def test_overlay_colorbar_draws_per_frame_dates():
    from app.tools.analysis_tools import _overlay_fixed_colorbar

    gif_bytes = _make_animated_gif(frames=2, size=(128, 96))

    with_dates = _overlay_fixed_colorbar(
        gif_bytes, vmin=0, vmax=10, title="Biomassa (T2G)\nton/ha",
        frame_dates=["01/2025", "02/2025"],
    )
    without_dates = _overlay_fixed_colorbar(
        gif_bytes, vmin=0, vmax=10, title="Biomassa (T2G)\nton/ha",
    )

    gif_dated = PILImage.open(BytesIO(with_dates))
    assert gif_dated.n_frames == 2
    # A barra de cores amplia o canvas para a direita
    assert gif_dated.size[0] > 128

    # O canto superior esquerdo deve diferir entre rodar com e sem data
    gif_dates = PILImage.open(BytesIO(with_dates))
    gif_dates.seek(0)
    corner_dated = gif_dates.convert("RGB").crop((0, 0, 60, 30))
    gif_plain = PILImage.open(BytesIO(without_dates))
    gif_plain.seek(0)
    corner_plain = gif_plain.convert("RGB").crop((0, 0, 60, 30))

    diff = ImageChops.difference(corner_dated, corner_plain).getbbox()
    assert diff is not None, "Rótulo de data não foi desenhado no canto"

    # Data do frame 2 deve estar presente no frame 2 (frames distintos)
    gif_dates.seek(1)
    frame2 = gif_dates.convert("RGB").crop((0, 0, 60, 30))
    gif_dates.seek(0)
    frame1 = gif_dates.convert("RGB").crop((0, 0, 60, 30))
    assert ImageChops.difference(frame1, frame2).getbbox() is not None


def test_overlay_colorbar_rejects_mismatched_dates():
    from app.tools.analysis_tools import _overlay_fixed_colorbar

    gif_bytes = _make_animated_gif(frames=2, size=(64, 48))

    with pytest.raises(RuntimeError, match="não corresponde"):
        _overlay_fixed_colorbar(
            gif_bytes, vmin=0, vmax=10, title="t",
            frame_dates=["01/2025"],
        )


# --- Integração real com GEE (gera GIF + converte para MP4 em tmp/) ---
def _load_first_mock_coords():
    import json

    mock_path = Path(__file__).resolve().parents[2] / "app/utils/mocks/new_property_mock.json"
    features = json.loads(mock_path.read_text())["features"]
    geom = features[0]["geometry"]
    return geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


@pytest.mark.integration
def test_retrieve_t2g_biomass_video_real_gee():
    today = datetime.date.today()
    coords = _load_first_mock_coords()

    # Janela curta (últimos 4 meses de referência) para manter o teste rápido.
    start_month = max(1, today.month - 3)
    result = retrieve_t2g_biomass_video(
        coords=coords,
        start_year=today.year,
        start_month=start_month,
        end_year=today.year,
        end_month=today.month,
    )

    if result is None:
        pytest.skip("Sem dados UGPP suficientes para a propriedade/período de teste")

    gif_bytes, effective_start, effective_end, frame_months, global_min, global_max = result
    assert len(gif_bytes) > 0
    assert gif_bytes[:6] == b"GIF89a" or gif_bytes[:6] == b"GIF87a"
    assert effective_start[0] >= BIOMASS_VIDEO_MIN_YEAR
    assert effective_end <= (today.year, today.month)
    assert global_min is not None and global_max is not None
    assert global_min <= global_max

    # Um (ano, mês) de acumulação por frame, todos >= 2025
    gif = PILImage.open(BytesIO(gif_bytes))
    assert len(frame_months) == gif.n_frames
    assert all(acc_year >= BIOMASS_VIDEO_MIN_YEAR and 1 <= acc_month <= 12 for acc_year, acc_month in frame_months)

    # O frame composto (satélite + biomassa + contorno) deve conter cores fora da
    # paleta de biomassa — evidência do fundo de satélite.
    gif.seek(0)
    frame_colors = gif.convert("RGB").getcolors(maxcolors=100000)
    assert frame_colors is not None and len(frame_colors) > 10, \
        f"Frame parece não ter fundo de satélite ({len(frame_colors) if frame_colors else '>100000'} cores)"

    # Pipeline completo da tool: datas por frame + colorbar fixa
    from app.tools.analysis_tools import _overlay_fixed_colorbar

    frame_dates = [f"{acc_month:02d}/{acc_year}" for acc_year, acc_month in frame_months]
    dated_gif_bytes = _overlay_fixed_colorbar(
        gif_bytes, vmin=global_min, vmax=global_max,
        title="Biomassa (T2G)\nton/ha", frame_dates=frame_dates,
    )
    dated_gif = PILImage.open(BytesIO(dated_gif_bytes))
    assert dated_gif.n_frames == gif.n_frames

    if _FFMPEG_AVAILABLE:
        mp4_bytes = gif_bytes_to_mp4_bytes(dated_gif_bytes)
        assert mp4_bytes[4:8] == b"ftyp"

    out_dir = Path("/tmp/opencode")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "biomass_video_test.gif").write_bytes(dated_gif_bytes)
    if _FFMPEG_AVAILABLE:
        (out_dir / "biomass_video_test.mp4").write_bytes(mp4_bytes)