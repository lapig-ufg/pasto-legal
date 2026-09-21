"""
Testes do vídeo de produtividade mensal de matéria seca.

Cobre a iteração de meses (`iterate_months`), a conversão GIF -> MP4
(`gif_bytes_to_mp4_bytes`) e um teste de integração opcional com o Earth Engine
que gera o vídeo real.

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

import ee

from app.services.geospatial.biomass.biomass_maps import (
    MONTHLY_SERIES_MIN_YEAR,
    iterate_months,
    render_monthly_productivity_video,
)
from app.services.video import gif_bytes_to_mp4_bytes

def _ffmpeg_available() -> bool:
    if shutil.which("ffmpeg"):
        return True
    ffmpeg_path = os.getenv("FFMPEG_PATH")
    return bool(ffmpeg_path) and shutil.which("ffmpeg", path=ffmpeg_path) is not None

_FFMPEG_AVAILABLE = _ffmpeg_available()


# --- iterate_months: intervalo válido ---
def test_iterate_months_simple_range():
    months, start, end = iterate_months(2025, 1, 2025, 3)
    assert months == [(2025, 1), (2025, 2), (2025, 3)]
    assert (start, end) == ((2025, 1), (2025, 3))


def test_iterate_months_crosses_year_boundary():
    months, _, _ = iterate_months(2025, 11, 2026, 2)
    assert months == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


def test_iterate_months_single_month():
    months, start, end = iterate_months(2025, 6, 2025, 6)
    assert months == [(2025, 6)]
    assert (start, end) == ((2025, 6), (2025, 6))


def test_iterate_months_inclusive_end():
    months, _, _ = iterate_months(2025, 1, 2025, 12)
    assert len(months) == 12
    assert months[-1] == (2025, 12)


# --- iterate_months: limite de ano inicial ---
def test_iterate_months_rejects_start_before_min_year():
    with pytest.raises(ValueError, match=str(MONTHLY_SERIES_MIN_YEAR)):
        iterate_months(2024, 6, 2025, 6)


def test_iterate_months_accepts_start_at_min_year():
    months, _, _ = iterate_months(MONTHLY_SERIES_MIN_YEAR, 1, 2025, 1)
    assert months == [(2025, 1)]


# --- iterate_months: clamp do fim no mês atual ---
def test_iterate_months_clamps_end_to_current_month():
    today = datetime.date.today()
    months, start, end = iterate_months(2025, 1, today.year + 1, 5)

    assert end == (today.year, today.month)
    assert months[-1] == (today.year, today.month)
    assert start == (2025, 1)


def test_iterate_months_keeps_end_within_current_month():
    today = datetime.date.today()
    past_year = MONTHLY_SERIES_MIN_YEAR if today.year > MONTHLY_SERIES_MIN_YEAR else today.year
    _, _, end = iterate_months(past_year, 1, today.year, max(1, today.month - 1))
    assert end[0] == today.year or end[0] == past_year
    assert end[1] <= today.month


# --- iterate_months: erros ---
def test_iterate_months_rejects_invalid_month():
    with pytest.raises(ValueError, match=r"entre 1 \(janeiro\) e 12"):
        iterate_months(2025, 0, 2025, 6)
    with pytest.raises(ValueError, match=r"entre 1 \(janeiro\) e 12"):
        iterate_months(2025, 1, 2025, 13)


def test_iterate_months_rejects_start_after_end():
    with pytest.raises(ValueError, match="anterior ou igual"):
        iterate_months(2025, 6, 2025, 1)


def test_iterate_months_rejects_start_after_current_month():
    today = datetime.date.today()
    future_month = today.month + 1 if today.month < 12 else 12
    future_year = today.year if today.month < 12 else today.year + 1
    with pytest.raises(ValueError):
        iterate_months(future_year, future_month, future_year, future_month)


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
        gif_bytes, vmin=0, vmax=10,
        title="Produtividade mensal de matéria seca estimada\nTime2Graze uGPP",
        unit="t MS/ha/mês",
        frame_dates=["01/2025", "02/2025"],
    )
    without_dates = _overlay_fixed_colorbar(
        gif_bytes, vmin=0, vmax=10,
        title="Produtividade mensal de matéria seca estimada\nTime2Graze uGPP",
        unit="t MS/ha/mês",
    )

    gif_dated = PILImage.open(BytesIO(with_dates))
    assert gif_dated.n_frames == 2
    # A barra de cores é anexada abaixo da imagem: a largura é preservada e a
    # altura cresce (título em cima, gradiente e rótulos embaixo).
    assert gif_dated.size[0] == 128
    assert gif_dated.size[1] > 96

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
            gif_bytes, vmin=0, vmax=10, title="t", unit="t MS/ha/mês",
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
def test_monthly_productivity_video_real_gee():
    today = datetime.date.today()
    roi = ee.Geometry.MultiPolygon(_load_first_mock_coords())

    # Janela curta (últimos 4 meses) para manter o teste rápido.
    start_month = max(1, today.month - 3)
    result = render_monthly_productivity_video(
        roi=roi,
        start_year=today.year,
        start_month=start_month,
        end_year=today.year,
        end_month=today.month,
    )

    if result is None:
        pytest.skip("Sem meses com dado suficientes para a propriedade/período de teste")

    gif_bytes = result["gif"]
    assert len(gif_bytes) > 0
    assert gif_bytes[:6] in (b"GIF89a", b"GIF87a")
    assert result["effective_start"][0] >= MONTHLY_SERIES_MIN_YEAR
    assert result["effective_end"] <= (today.year, today.month)
    assert result["vmin"] is not None and result["vmax"] is not None
    assert result["vmin"] <= result["vmax"]

    # Um (ano, mês) por frame, todos na série mensal
    gif = PILImage.open(BytesIO(gif_bytes))
    assert len(result["months"]) == gif.n_frames
    assert all(
        year >= MONTHLY_SERIES_MIN_YEAR and 1 <= month <= 12
        for year, month in result["months"]
    )

    # Toda estimativa do vídeo é produtividade mensal, na unidade certa
    for estimate in result["estimates"]:
        assert estimate.metric_type == "monthly_dry_matter_productivity"
        assert estimate.unit_per_ha == "t_DM_ha_month"
        assert 0.0 <= estimate.value_per_ha <= 6.0

    # O frame composto (satélite + camada + contorno) deve conter cores fora da
    # paleta da métrica — evidência do fundo de satélite.
    gif.seek(0)
    frame_colors = gif.convert("RGB").getcolors(maxcolors=100000)
    assert frame_colors is not None and len(frame_colors) > 10, \
        f"Frame parece não ter fundo de satélite ({len(frame_colors) if frame_colors else '>100000'} cores)"

    # Pipeline completo da tool: datas por frame + colorbar fixa na unidade da métrica
    from app.tools.analysis_tools import _overlay_fixed_colorbar

    reference = result["estimates"][0]
    frame_dates = [f"{month:02d}/{year}" for year, month in result["months"]]
    dated_gif_bytes = _overlay_fixed_colorbar(
        gif_bytes,
        vmin=result["vmin"],
        vmax=result["vmax"],
        title=f"{reference.metric_label}\n{reference.source}",
        unit=reference.unit_label,
        frame_dates=frame_dates,
    )
    dated_gif = PILImage.open(BytesIO(dated_gif_bytes))
    assert dated_gif.n_frames == gif.n_frames

    if _FFMPEG_AVAILABLE:
        mp4_bytes = gif_bytes_to_mp4_bytes(dated_gif_bytes)
        assert mp4_bytes[4:8] == b"ftyp"
