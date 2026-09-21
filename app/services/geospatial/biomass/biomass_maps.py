"""Renderização dos mapas e do vídeo das métricas de biomassa.

Cada mapa é renderizado a partir de uma `BiomassEstimate`, e não de uma imagem
solta: é isso que garante que a barra de cores traga a métrica, a fonte, o
período e a unidade corretos, e que a escala de cores esteja na unidade final
(t MS/ha) em vez de em valor bruto do asset.
"""

import datetime
import traceback

from io import BytesIO
from typing import List, Optional, Tuple

import ee
import PIL
import requests

from agno.utils.log import log_error, log_warning

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.biomass_productivity import (
    MONTH_NAMES,
    annual_productivity_image,
    estimate_monthly_productivity,
    monthly_period,
    monthly_productivity_image,
)
from app.services.geospatial.biomass.biomass_reporting import BIOMASS_PALETTE, annotate_map
from app.services.geospatial.biomass.pasture_mask import PastureMask, build_pasture_mask


# A série Time2Graze começa em 2025; antes disso só há a série anual do MapBiomas.
MONTHLY_SERIES_MIN_YEAR = 2025


def _render_layer(
    roi: ee.Geometry,
    layer: ee.Image,
    vmin: float,
    vmax: float,
    base_year: int,
) -> "PIL.Image.Image":
    """
    Compõe a camada temática sobre a imagem de satélite e o contorno do imóvel.

    Args:
        roi (ee.Geometry): Região de interesse.
        layer (ee.Image): Camada temática a sobrepor.
        vmin (float): Mínimo da escala de cores, na unidade final.
        vmax (float): Máximo da escala de cores, na unidade final.
        base_year (int): Ano da imagem de satélite de fundo.

    Returns:
        PIL.Image.Image: Mapa composto, ainda sem a barra de cores.
    """
    from app.services.geospatial.gee import (
        _FEATURE_BUFFER,
        _IMAGE_DIMENSION,
        _draw_feature_boundaries,
        _get_base_image,
    )

    visualized = layer.visualize(min=vmin, max=vmax, palette=BIOMASS_PALETTE)
    base = _get_base_image(roi=roi, year=base_year)
    outline = _draw_feature_boundaries(roi=roi)

    composed = (
        base.blend(visualized.clip(roi))
        .blend(outline)
        .clip(roi.buffer(_FEATURE_BUFFER).bounds())
    )

    url = composed.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    return PIL.Image.open(BytesIO(response.content))


def _value_range(image: ee.Image, roi: ee.Geometry, scale: float) -> Tuple[float, float]:
    """
    Faixa de valores da camada, já na unidade final da métrica.

    Args:
        image (ee.Image): Camada temática.
        roi (ee.Geometry): Região de interesse.
        scale (float): Escala de redução, em metros.

    Returns:
        Tuple[float, float]: (mínimo, máximo).

    Raises:
        ValueError: Se não houver pixel válido na área.
    """
    stats = image.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=roi,
        scale=scale,
        maxPixels=1e13,
    ).getInfo()

    minimum = next((stats[key] for key in stats if key.endswith("_min")), None)
    maximum = next((stats[key] for key in stats if key.endswith("_max")), None)

    if minimum is None or maximum is None:
        raise ValueError(
            "Não há pastagem mapeada com dado válido nesta área para o período pedido."
        )

    return float(minimum), float(maximum)


def render_monthly_productivity_map(
    roi: ee.Geometry,
    year: int,
    month: int,
    mask: Optional[PastureMask] = None,
    today: Optional[datetime.date] = None,
) -> Optional[Tuple["PIL.Image.Image", BiomassEstimate]]:
    """
    Mapa da produtividade mensal de matéria seca (t MS/ha/mês).

    Args:
        roi (ee.Geometry): Região de interesse.
        year (int): Ano do mês a mapear.
        month (int): Mês a mapear (1-12).
        mask (PastureMask, optional): Máscara de pastagem; None constrói a oficial.
        today (datetime.date, optional): Data de referência.

    Returns:
        tuple | None: (mapa com barra de cores, estimativa correspondente), ou
        None quando não há dado mensal para o período.
    """
    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

    estimate = estimate_monthly_productivity(
        roi=roi, year=year, month=month, mask=pasture_mask, today=today
    )
    if estimate is None:
        return None

    period_start, period_end = monthly_period(year=year, month=month, today=today)
    layer = monthly_productivity_image(
        roi=roi, period_start=period_start, period_end=period_end, mask=pasture_mask
    )[0]

    vmin, vmax = _value_range(layer, roi, estimate.raster_resolution_m)
    image = _render_layer(roi=roi, layer=layer, vmin=vmin, vmax=vmax, base_year=year)

    return annotate_map(image, estimate, vmin=vmin, vmax=vmax), estimate



def render_annual_productivity_map(
    roi: ee.Geometry,
    year: int,
    mask: Optional[PastureMask] = None,
) -> Tuple["PIL.Image.Image", BiomassEstimate]:
    """
    Mapa da produtividade anual de matéria seca (t MS/ha/ano), série MapBiomas.

    Os valores da barra de cores são os próprios valores de pixel, que já estão
    em t MS/ha/ano: não há escala a aplicar na legenda.

    Args:
        roi (ee.Geometry): Região de interesse.
        year (int): Ano a mapear.
        mask (PastureMask, optional): Máscara adicional de pastagem.

    Returns:
        Tuple[PIL.Image.Image, BiomassEstimate]: Mapa com barra de cores e estimativa.

    Raises:
        ValueError: Se o ano não existir no asset ou não houver pastagem mapeada.
    """
    from app.services.geospatial.biomass.biomass_productivity import estimate_annual_productivity

    estimate = estimate_annual_productivity(roi=roi, year=year, mask=mask)
    layer = annual_productivity_image(roi=roi, year=year, mask=mask)

    vmin, vmax = _value_range(layer, roi, estimate.raster_resolution_m)
    image = _render_layer(roi=roi, layer=layer, vmin=vmin, vmax=vmax, base_year=year)

    return annotate_map(image, estimate, vmin=vmin, vmax=vmax), estimate


def iterate_months(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    today: Optional[datetime.date] = None,
) -> Tuple[List[Tuple[int, int]], Tuple[int, int], Tuple[int, int]]:
    """
    Normaliza o intervalo de meses do vídeo, limitando-o à série disponível.

    Args:
        start_year (int): Ano inicial pedido.
        start_month (int): Mês inicial pedido (1-12).
        end_year (int): Ano final pedido (inclusivo).
        end_month (int): Mês final pedido (1-12, inclusivo).
        today (datetime.date, optional): Data de referência.

    Returns:
        tuple: (lista de (ano, mês), início efetivo, fim efetivo).

    Raises:
        ValueError: Se os meses forem inválidos, o ano inicial anteceder a série
            ou o intervalo ficar vazio após o ajuste.
    """
    reference = today or datetime.date.today()

    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        raise ValueError("Os meses informados devem estar entre 1 (janeiro) e 12 (dezembro).")

    if start_year < MONTHLY_SERIES_MIN_YEAR:
        raise ValueError(
            f"A série mensal de produtividade começa em {MONTHLY_SERIES_MIN_YEAR}. "
            f"Informe um ano inicial maior ou igual a {MONTHLY_SERIES_MIN_YEAR}, ou peça "
            "a série anual do MapBiomas para anos anteriores."
        )

    limit = (reference.year, reference.month)
    if (end_year, end_month) > limit:
        log_warning(
            f"iterate_months: fim {end_month}/{end_year} ajustado para o mês corrente "
            f"{limit[1]}/{limit[0]}"
        )
        end_year, end_month = limit

    effective_start = (start_year, start_month)
    effective_end = (end_year, end_month)

    if effective_start > effective_end:
        raise ValueError(
            "O mês/ano inicial deve ser anterior ou igual ao mês/ano final "
            "(o período final é limitado ao mês corrente)."
        )

    months: List[Tuple[int, int]] = []
    year, month = effective_start
    while (year, month) <= effective_end:
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    return months, effective_start, effective_end


def render_monthly_productivity_video(
    roi: ee.Geometry,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    mask: Optional[PastureMask] = None,
    today: Optional[datetime.date] = None,
) -> Optional[dict]:
    """
    GIF da evolução mensal da produtividade, com escala de cores fixa entre frames.

    Args:
        roi (ee.Geometry): Região de interesse.
        start_year (int): Ano do primeiro mês.
        start_month (int): Mês inicial (1-12).
        end_year (int): Ano do último mês.
        end_month (int): Mês final (1-12).
        mask (PastureMask, optional): Máscara de pastagem reaproveitada entre frames.
        today (datetime.date, optional): Data de referência.

    Returns:
        dict | None: {"gif", "months", "vmin", "vmax", "effective_start",
        "effective_end", "estimates"}, ou None quando menos de dois meses têm dado.

    Raises:
        ValueError: Se o intervalo for inválido.
        RuntimeError: Em falhas de processamento, servidor ou conexão.
    """
    from app.services.geospatial.gee import (
        _FEATURE_BUFFER,
        _IMAGE_DIMENSION,
        _draw_feature_boundaries,
        _get_base_image,
    )

    try:
        months, effective_start, effective_end = iterate_months(
            start_year, start_month, end_year, end_month, today=today
        )

        pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

        layers: List[Tuple[int, int, ee.Image]] = []
        estimates: List[BiomassEstimate] = []
        vmin: Optional[float] = None
        vmax: Optional[float] = None

        for year, month in months:
            estimate = estimate_monthly_productivity(
                roi=roi, year=year, month=month, mask=pasture_mask, today=today
            )
            if estimate is None:
                log_warning(
                    f"render_monthly_productivity_video: sem dado para "
                    f"{MONTH_NAMES[month]}/{year}; frame ignorado"
                )
                continue

            period_start, period_end = monthly_period(year=year, month=month, today=today)
            layer = monthly_productivity_image(
                roi=roi, period_start=period_start, period_end=period_end, mask=pasture_mask
            )[0]

            try:
                frame_min, frame_max = _value_range(layer, roi, estimate.raster_resolution_m)
            except ValueError:
                log_warning(
                    f"render_monthly_productivity_video: estatísticas vazias para "
                    f"{MONTH_NAMES[month]}/{year}; frame ignorado"
                )
                continue

            vmin = frame_min if vmin is None else min(vmin, frame_min)
            vmax = frame_max if vmax is None else max(vmax, frame_max)
            layers.append((year, month, layer))
            estimates.append(estimate)

        if len(layers) < 2:
            log_warning(
                f"render_monthly_productivity_video: apenas {len(layers)} mês(es) com dado "
                f"entre {effective_start} e {effective_end}; retornando None"
            )
            return None

        outline = _draw_feature_boundaries(roi=roi)
        region = roi.buffer(_FEATURE_BUFFER).bounds()
        bases = {year: _get_base_image(roi=roi, year=year) for year, _, _ in layers}

        frames = [
            bases[year]
            .blend(layer.visualize(min=vmin, max=vmax, palette=BIOMASS_PALETTE).clip(roi))
            .blend(outline)
            .clip(region)
            for year, _, layer in layers
        ]

        url = ee.ImageCollection.fromImages(frames).getVideoThumbURL({
            "dimensions": _IMAGE_DIMENSION,
            "region": region,
            "framesPerSecond": 2,
            "format": "gif",
        })

        response = requests.get(url, timeout=120)
        response.raise_for_status()

        return {
            "gif": response.content,
            "months": [(year, month) for year, month, _ in layers],
            "vmin": vmin,
            "vmax": vmax,
            "effective_start": effective_start,
            "effective_end": effective_end,
            "estimates": estimates,
        }

    except ValueError:
        raise
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {error}"
        )
    except requests.exceptions.HTTPError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "O servidor de imagens do satélite retornou um erro ao gerar o vídeo. "
            f"Tente novamente em alguns instantes. Detalhes: {error}"
        )
    except requests.exceptions.RequestException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Não foi possível baixar o vídeo por falha de conexão. Detalhes: {error}"
        )
