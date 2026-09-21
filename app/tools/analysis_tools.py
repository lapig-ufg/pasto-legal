import datetime

from io import BytesIO

import PIL

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import File, Image, Video
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description, get_tool_result_text
from app.hooks.tool_hooks import validate_selected_property_hook
from app.services.video import gif_bytes_to_mp4_bytes
from app.services.geospatial.image import append_continuous_colorbar, draw_corner_label
from app.services.geospatial.gee import (
    retrieve_feature_images,
    retrieve_pasture_vigor_image,
    retrieve_feature_soil_texture_image,
    query_pasture_statistics,
    query_topographic_stats,
    )
from app.services.geospatial.biomass.biomass_assessment import assess_property_biomass
from app.services.geospatial.biomass.biomass_charts import render_historical_series_chart
from app.services.geospatial.biomass.biomass_maps import (
    render_annual_productivity_map,
    render_monthly_productivity_map,
    render_monthly_productivity_video,
)
from app.services.geospatial.biomass.biomass_reporting import BIOMASS_PALETTE, map_caption
from app.services.geospatial.biomass.historical_biomass import (
    export_historical_series,
    historical_series,
)
from app.services.geospatial.biomass.pasture_mask import build_pasture_mask
from app.services.geospatial.pasture_classification import classify_pasture_on_the_fly
from app.services.boletim_scripts import build_boletim_chat_summary, build_boletim_story
from app.services.pdf_scripts import render_document
from app.schemas.property_stats import PastureStats, PropertyStats, TopographicStats
from app.utils.feature_utils import resolve_feature
import ee


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_property_image"))
def generate_property_image(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural,
    incluindo a delimitação geográfica, com base nos últimos dois meses.

    Use apenas quando o usuário pedir para visualizar a propriedade.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Imagem PNG da visão aérea com delimitação geográfica.
    """
    log_debug(f"generate_property_image: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_property_image", "feature_not_found", feature_id=feature_id))

        img = retrieve_feature_images(coords=selected_property.get_coords())[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        log_debug(f"generate_property_image: imagem gerada ({selected_property.id})")
        return ToolResult(
            content=get_tool_result_text("analysis_tools", "generate_property_image", "success_contour_legend"),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_property_image: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_property_image", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_biomass_image"))
def generate_biomass_image(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera o mapa de produtividade de matéria seca da propriedade rural.

    Tenta primeiro a produtividade MENSAL (t MS/ha/mês, série Time2Graze de 10 m).
    Quando não há dado mensal para a propriedade, cai para a produtividade ANUAL
    do MapBiomas (t MS/ha/ano) e diz explicitamente que a métrica mudou — as duas
    não são intercambiáveis.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Mapa em PNG com a barra de cores identificando métrica,
        fonte, período e unidade.
    """
    log_debug(f"generate_biomass_image: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_biomass_image", "feature_not_found", feature_id=feature_id))

        roi = ee.Geometry.MultiPolygon(selected_property.get_coords())
        today = datetime.date.today()
        mask = build_pasture_mask(roi=roi, strategy="official")

        result = _latest_monthly_map(roi=roi, mask=mask, today=today)

        if result is not None:
            image, estimate = result

            buffer = BytesIO()
            image.save(buffer, format="PNG")

            log_debug(
                f"generate_biomass_image: mapa mensal gerado ({selected_property.id}, "
                f"{estimate.period_label()})"
            )
            return ToolResult(content=map_caption(estimate), images=[Image(content=buffer.getvalue())])

        image, estimate = render_annual_productivity_map(roi=roi, year=None, mask=None)

        buffer = BytesIO()
        image.save(buffer, format="PNG")

        log_debug(f"generate_biomass_image: mapa anual gerado ({selected_property.id})")
        return ToolResult(
            content=get_tool_result_text(
                "analysis_tools", "generate_biomass_image", "monthly_unavailable_annual_fallback",
                metadata=map_caption(estimate),
            ),
            images=[Image(content=buffer.getvalue())],
        )

    except Exception as e:
        log_error(f"generate_biomass_image: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_biomass_image", "error", error=e))


def _latest_monthly_map(roi, mask, today: datetime.date, lookback_months: int = 18):
    """
    Mapa mensal do mês mais recente com dado, procurando para trás.

    O mês efetivamente mapeado vai na barra de cores e na legenda, de modo que a
    substituição do mês pedido nunca é silenciosa.

    Args:
        roi (ee.Geometry): Região de interesse.
        mask (PastureMask): Máscara de pastagem reaproveitada entre tentativas.
        today (datetime.date): Data de referência.
        lookback_months (int): Quantos meses procurar para trás.

    Returns:
        tuple | None: (mapa, estimativa) do mês mais recente com dado, ou None.
    """
    year, month = today.year, today.month

    for _ in range(lookback_months):
        result = render_monthly_productivity_map(
            roi=roi, year=year, month=month, mask=mask, today=today
        )
        if result is not None:
            return result

        month -= 1
        if month == 0:
            year, month = year - 1, 12

    return None


def _overlay_fixed_colorbar(
    gif_bytes: bytes,
    vmin: float,
    vmax: float,
    title: str,
    unit: str,
    frame_dates: list[str] | None = None,
) -> bytes:
    """
    Sobrepõe uma barra de cores fixa (escala global) em todos os frames de um GIF,
    e opcionalmente um rótulo de data (canto superior esquerdo) por frame.

    Args:
        gif_bytes (bytes): Conteúdo do GIF animado de entrada.
        vmin (float): Valor mínimo global da escala, na unidade da métrica.
        vmax (float): Valor máximo global da escala, na unidade da métrica.
        title (str): Título exibido acima da imagem; a barra de cores abaixo
            indica os valores mínimo, intermediário e máximo, com a unidade
            no rótulo máximo.
        unit (str): Unidade da métrica no rótulo máximo (ex.: "t MS/ha/mês").
        frame_dates (list[str] | None): Rótulo de data para cada frame
            (ex.: "08/2025"), na ordem dos frames. None omite os rótulos.

    Returns:
        bytes: GIF reencodado com a barra de cores (e datas) em todos os frames.

    Raises:
        RuntimeError: Quando o GIF não pode ser decodificado, reencodado, ou
            quando a quantidade de datas não corresponde à de frames.
    """
    try:
        gif = PIL.Image.open(BytesIO(gif_bytes))

        n_frames = getattr(gif, "n_frames", 1)
        if frame_dates is not None and len(frame_dates) != n_frames:
            raise RuntimeError(
                f"Quantidade de datas ({len(frame_dates)}) não corresponde ao número "
                f"de frames ({n_frames}) do vídeo."
            )

        frames_with_colorbar: list[PIL.Image.Image] = []
        duration_ms = []
        frame_index = 0
        while True:
            try:
                duration_ms.append(gif.info.get("duration", 500))
            except (AttributeError, KeyError):
                duration_ms.append(500)

            frame = gif.convert("RGB")
            if frame_dates is not None:
                frame = draw_corner_label(frame, frame_dates[frame_index])

            frames_with_colorbar.append(
                append_continuous_colorbar(
                    frame,
                    title=title,
                    vmin=round(vmin, 2),
                    vmax=round(vmax, 2),
                    unit=unit,
                    palette=BIOMASS_PALETTE,
                )
            )
            frame_index += 1
            try:
                gif.seek(gif.tell() + 1)
            except EOFError:
                break

        buffer = BytesIO()
        frames_with_colorbar[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=frames_with_colorbar[1:],
            duration=duration_ms or None,
            loop=0,
        )
        return buffer.getvalue()

    except RuntimeError:
        raise
    except Exception as e:
        log_error(f"_overlay_fixed_colorbar: {e}")
        raise RuntimeError(f"Falha ao adicionar a barra de cores ao vídeo. Detalhes: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_biomass_video"))
def generate_biomass_video(
    run_context: RunContext,
    feature_id: str,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> ToolResult:
    """
    Gera um vídeo (MP4) animado mostrando a evolução mensal da biomassa (matéria seca,
    ton/ha) acumulada na propriedade rural, mês a mês, sobre a imagem de satélite.

    Cada frame corresponde ao acumulado do mês anterior ao mês de referência
    (mesma regra do mapa de biomassa), com escala de cores fixa entre os frames
    para permitir comparação direta entre os meses, e indica no canto superior
    esquerdo o mês de acumulação do frame.

    Limitações: dados disponíveis a partir de 2025; o período final é limitado ao
    mês atual. Meses sem dados do satélite (UGPP) são omitidos; se houver menos de
    dois meses com dados, o vídeo não é gerado.

    A geração consulta o satélite para cada mês do intervalo e pode levar dezenas
    de segundos. Use apenas quando o usuário pedir explicitamente um vídeo,
    animação ou evolução temporal da biomassa.

    params:
        feature_id (str): Identificador (id) da feição registrada.
        start_year (int): Ano inicial do vídeo (mínimo 2025).
        start_month (int): Mês inicial (1 a 12).
        end_year (int): Ano final (limitado ao mês atual).
        end_month (int): Mês final (1 a 12, limitado ao mês atual).

    Return:
        ToolResult: Vídeo MP4 da evolução mensal da biomassa.
    """
    log_debug(
        f"generate_biomass_video: feature_id={feature_id}, "
        f"period={start_month}/{start_year} - {end_month}/{end_year}"
    )
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_biomass_video", "feature_not_found", feature_id=feature_id))

        result = render_monthly_productivity_video(
            roi=ee.Geometry.MultiPolygon(selected_property.get_coords()),
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )

        if result is None:
            log_warning(f"generate_biomass_video: meses com dado insuficientes ({selected_property.id})")
            return ToolResult(
                content=get_tool_result_text(
                    "analysis_tools", "generate_biomass_video", "insufficient_data",
                    start_month=start_month, start_year=start_year,
                    end_month=end_month, end_year=end_year,
                )
            )

        effective_start = result["effective_start"]
        effective_end = result["effective_end"]
        reference = result["estimates"][0]

        frame_dates = [f"{month:02d}/{year}" for year, month in result["months"]]
        gif_bytes = _overlay_fixed_colorbar(
            result["gif"],
            vmin=result["vmin"],
            vmax=result["vmax"],
            title=f"{reference.metric_label}\n{reference.source}",
            unit=reference.unit_label,
            frame_dates=frame_dates,
        )
        mp4_bytes = gif_bytes_to_mp4_bytes(gif_bytes)

        log_debug(
            f"generate_biomass_video: vídeo gerado ({selected_property.id}, "
            f"{effective_start[1]}/{effective_start[0]} - {effective_end[1]}/{effective_end[0]})"
        )
        return ToolResult(
            content=get_tool_result_text(
                "analysis_tools", "generate_biomass_video", "success",
                metric=reference.metric_label,
                source=reference.source,
                unit=reference.unit_label,
                resolution=f"{reference.raster_resolution_m:g}",
                mask=f"{reference.pasture_mask_source}, {reference.effective_mask_resolution_m:g} m",
                start=f"{effective_start[1]:02d}/{effective_start[0]}",
                end=f"{effective_end[1]:02d}/{effective_end[0]}",
                min=f"{result['vmin']:.2f}",
                max=f"{result['vmax']:.2f}",
            ),
            videos=[Video(content=mp4_bytes, mime_type="video/mp4", format="mp4")],
        )

    except Exception as e:
        log_error(f"generate_biomass_video: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_biomass_video", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_historical_biomass_series"))
def generate_historical_biomass_series(
    run_context: RunContext,
    feature_id: str,
    start_year: int = 2000,
    end_year: int = 2024,
) -> ToolResult:
    """
    Gera a série histórica anual de produtividade de matéria seca (2000-2024) da
    propriedade, calculada on-the-fly sobre as áreas de pastagem, com gráfico.

    A fonte é o GPP anual do Global Pasture Watch, convertido em matéria seca pela
    eficiência do uso do carbono e pela razão carbono -> matéria seca. É
    produtividade ANUAL (t MS/ha/ano): não é biomassa em pé nem forragem disponível,
    e não representa a condição atual do pasto.

    Além do gráfico, exporta todos os pixels da propriedade para zarr (S3 em
    produção), para reuso analítico.

    params:
        feature_id (str): Identificador (id) da feição registrada.
        start_year (int): Primeiro ano da série (mínimo 2000).
        end_year (int): Último ano da série (máximo 2024).

    Return:
        ToolResult: Gráfico PNG da série com faixa de incerteza, mais o resumo
        textual com fonte, período, unidade, resolução e limitações.
    """
    log_debug(
        f"generate_historical_biomass_series: feature_id={feature_id}, "
        f"period={start_year}-{end_year}"
    )
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_historical_biomass_series", "feature_not_found", feature_id=feature_id))

        roi = ee.Geometry.MultiPolygon(selected_property.get_coords())
        mask = build_pasture_mask(roi=roi, strategy="official")

        estimates = historical_series(
            roi=roi, start_year=start_year, end_year=end_year, mask=mask
        )

        if not estimates:
            log_warning(f"generate_historical_biomass_series: série vazia ({selected_property.id})")
            return ToolResult(
                content=get_tool_result_text(
                    "analysis_tools", "generate_historical_biomass_series", "no_data",
                    start_year=start_year, end_year=end_year,
                )
            )

        chart = render_historical_series_chart(estimates)
        buffer = BytesIO()
        chart.save(buffer, format="PNG")

        # A exportação pixel a pixel não pode derrubar a entrega do gráfico.
        export = _safe_fetch_image(
            "exportação zarr da série histórica",
            lambda: export_historical_series(
                roi=roi, feature_id=selected_property.id,
                start_year=start_year, end_year=end_year, mask=mask,
            ),
        )

        first, last = estimates[0], estimates[-1]
        change = (
            0.0 if first.value_per_ha in (None, 0)
            else (last.value_per_ha - first.value_per_ha) / first.value_per_ha * 100
        )

        log_debug(
            f"generate_historical_biomass_series: {len(estimates)} ano(s) "
            f"({selected_property.id})"
        )
        return ToolResult(
            content=get_tool_result_text(
                "analysis_tools", "generate_historical_biomass_series", "success",
                n_years=len(estimates),
                start_year=first.period_start.year,
                end_year=last.period_start.year,
                first_value=f"{first.value_per_ha:.2f}",
                last_value=f"{last.value_per_ha:.2f}",
                change=f"{change:+.1f}",
                metadata=last.to_report_block(),
                export=("" if export is None else f" Pixels exportados para {export['path']}."),
            ),
            images=[Image(content=buffer.getvalue())],
        )

    except Exception as e:
        log_error(f"generate_historical_biomass_series: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_historical_biomass_series", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook])
def generate_pasture_classification_image(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera o mapa de classificação de pastagem (pasto x não-pasto) da propriedade rural,
    calculado sob demanda ("on-the-fly") para o ano mais recente disponível.

    Diferente de `get_pasture_stats` (que usa o mapeamento oficial do MapBiomas, sempre
    com pelo menos um ano de atraso), esta ferramenta classifica a propriedade em tempo real
    usando o ano de satélite mais recente disponível, útil quando o usuário quer o mapeamento
    de uso do solo mais atualizado possível.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Mapa em PNG (verde = pastagem) e a área de pastagem em hectares.
    """
    log_debug(f"generate_pasture_classification_image: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_pasture_classification_image", "feature_not_found", feature_id=feature_id))

        roi = ee.Geometry.MultiPolygon(selected_property.get_coords())
        result = classify_pasture_on_the_fly(roi=roi, feature_id=selected_property.id)

        buffer = BytesIO()
        result["imagem"].save(buffer, format="PNG")

        log_debug(f"generate_pasture_classification_image: classificação gerada ({selected_property.id}, {result['area_pasto_ha']} ha)")
        return ToolResult(
            content=get_tool_result_text(
                "analysis_tools", "generate_pasture_classification_image", "success_area_legend",
                pred_year=result['pred_year'], pasture_area_ha=result['area_pasto_ha'],
            ),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_pasture_classification_image: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_pasture_classification_image", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_soil_texture_image"))
def generate_soil_texture_image(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera um mapa temático da textura do solo sobre os limites da propriedade rural na profundidade de 0 a 30cm.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    log_debug(f"generate_soil_texture_image: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_soil_texture_image", "feature_not_found", feature_id=feature_id))

        img = retrieve_feature_soil_texture_image(coords=selected_property.get_coords())

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        log_debug(f"generate_soil_texture_image: mapa de solo gerado ({selected_property.id})")
        return ToolResult(
            content=get_tool_result_text("analysis_tools", "generate_soil_texture_image", "success_soil_legend"),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_soil_texture_image: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_soil_texture_image", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "get_pasture_stats"))
def get_pasture_stats(run_context: RunContext, feature_id: str):
    """
    Recupera produtividade de matéria seca, vigor vegetativo, idade da pastagem e
    classificação de uso do solo mais recentes.

    As métricas de biomassa vêm separadas por conceito — produtividade mensal
    (t MS/ha/mês), produtividade anual (t MS/ha/ano), biomassa em pé (t MS/ha) e
    forragem disponível (t MS/ha) — cada uma com fonte, período, unidade, resolução,
    cobertura válida e incerteza. Métricas indisponíveis são declaradas como tal;
    NUNCA apresente uma no lugar da outra.

    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Produtividade, biomassa ou forragem disponível.
    - Capacidade de suporte e lotação.
    - Classificação de uso do solo (LULC) incluindo: Silvicultura, Cana, Soja, Arroz, Café, Citrus, etc.
    - Idade da pastagem.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        Dicionário contendo a área de biomassa, vigor da pastagem, idade e uso e cobertura do solo.
    """
    log_debug(f"get_pasture_stats: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "get_pasture_stats", "feature_not_found", feature_id=feature_id))

        coords = selected_property.get_coords()
        today = datetime.date.today()

        assessment = assess_property_biomass(
            roi=ee.Geometry.MultiPolygon(coords), today=today
        )
        new_pasture_stats: PastureStats = query_pasture_statistics(
            coords=coords, month=today.month, year=today.year, include_biomass=False
        )

        log_debug(f"get_pasture_stats: stats recuperadas ({selected_property.id})")
        return ToolResult(content=f"{assessment}\n\n{new_pasture_stats}")
    except Exception as e:
        log_error(f"get_pasture_stats: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "get_pasture_stats", "error", error=e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "get_topographic_stats"))
def get_topographic_stats(run_context: RunContext, feature_id: str):
    """
    Recupera estatísticas de topografia da propriedade (altimetria e declividade).

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        Dicionário contendo as informações de altimetria e declividade.
    """
    log_debug(f"get_topographic_stats: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "get_topographic_stats", "feature_not_found", feature_id=feature_id))

        new_topographic_stats: TopographicStats = query_topographic_stats(coords=selected_property.get_coords())

        log_debug(f"get_topographic_stats: stats recuperadas ({selected_property.id})")
        return ToolResult(content=str(new_topographic_stats))
    except Exception as e:
        log_error(f"get_topographic_stats: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "get_topographic_stats", "error", error=e))


def _pil_to_png_bytes(img) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _fetch_biomass_map(roi, mask, today: datetime.date) -> tuple:
    """
    Mapa da métrica de produtividade mais recente disponível, com a sua legenda.

    Prefere a produtividade mensal; sem ela, cai para a anual — e a legenda diz
    qual métrica está no mapa, para que o leitor não confunda as duas.

    Args:
        roi (ee.Geometry): Região de interesse.
        mask (PastureMask): Máscara de pastagem já construída pela avaliação.
        today (datetime.date): Data de referência.

    Returns:
        tuple: (imagem PIL ou None, legenda da figura).
    """
    monthly = _safe_fetch_image(
        "mapa de produtividade mensal", lambda: _latest_monthly_map(roi=roi, mask=mask, today=today)
    )
    if monthly is not None:
        image, estimate = monthly
        return image, f"{estimate.metric_label} - {estimate.period_label()}"

    annual = _safe_fetch_image(
        "mapa de produtividade anual", lambda: render_annual_productivity_map(roi=roi, year=None)
    )
    if annual is not None:
        image, estimate = annual
        return image, f"{estimate.metric_label} - {estimate.period_label()}"

    return None, "Mapa de produtividade de matéria seca"


def _safe_fetch_image(label: str, fetch_fn):
    """Busca um mapa 'extra' do boletim sem derrubar o PDF inteiro se essa camada específica falhar."""
    try:
        return fetch_fn()
    except Exception as error:
        log_error(f"{label} indisponível para o boletim: {error}")
        return None


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_property_boletim"))
def generate_property_boletim(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera um boletim em PDF consolidando as análises da propriedade rural — localização,
    classificação de pastagem, produtividade/biomassa/forragem, vigor e tipos de solo —
    com os mapas correspondentes, pronto para compartilhar com agrônomos ou parceiros.

    IMPORTANTE: a seção de biomassa traz cada métrica separada (produtividade mensal,
    produtividade anual, biomassa em pé, forragem disponível e capacidade de suporte),
    com a sua fonte, período, unidade, resolução e incerteza; métricas indisponíveis
    aparecem declaradas como indisponíveis. Idade, vigor e uso do solo (LULC) refletem
    o ano mais recente disponível no MapBiomas. Avise o usuário sobre essa defasagem
    ao entregar o boletim.

    Use apenas quando o usuário pedir explicitamente um boletim, relatório ou PDF
    para compartilhar ou baixar. A geração consulta o satélite e gera vários mapas em
    tempo real, podendo levar dezenas de segundos.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Arquivo PDF do boletim com dados e mapas reais da propriedade.
    """
    log_debug(f"generate_property_boletim: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=get_tool_result_text("analysis_tools", "generate_property_boletim", "feature_not_found", feature_id=feature_id))

        coords = selected_property.get_coords()
        today = datetime.date.today()

        roi = ee.Geometry.MultiPolygon(coords)

        pasture_stats = query_pasture_statistics(
            coords=coords, month=today.month, year=today.year, include_biomass=False
        )
        stats = PropertyStats(car_code=selected_property.id or selected_property.get_metadata("car_code") or "", list_pasture_stats=[pasture_stats])

        assessment = assess_property_biomass(roi=roi, today=today)

        location_image = retrieve_feature_images(coords)[0]

        pasture_result = classify_pasture_on_the_fly(roi=roi, feature_id=selected_property.id)
        pasture_map_image = pasture_result["imagem"]

        biomass_map_image, biomass_map_caption = _fetch_biomass_map(
            roi=roi, mask=assessment.mask, today=today
        )
        vigor_map_image = _safe_fetch_image("mapa de vigor", lambda: retrieve_pasture_vigor_image(coords))
        soil_map_image = _safe_fetch_image("mapa de textura do solo", lambda: retrieve_feature_soil_texture_image(coords))

        story = build_boletim_story(
            selected_property,
            stats,
            location_image_bytes=_pil_to_png_bytes(location_image),
            pasture_map_image_bytes=_pil_to_png_bytes(pasture_map_image),
            vigor_map_image_bytes=_pil_to_png_bytes(vigor_map_image) if vigor_map_image else None,
            biomass_map_image_bytes=_pil_to_png_bytes(biomass_map_image) if biomass_map_image else None,
            soil_map_image_bytes=_pil_to_png_bytes(soil_map_image) if soil_map_image else None,
            biomass_assessment=assessment,
            biomass_map_caption=biomass_map_caption,
        )
        pdf_bytes = render_document(story)

        log_debug(f"generate_property_boletim: boletim gerado ({selected_property.id})")
        return ToolResult(
            content=build_boletim_chat_summary(selected_property, pasture_stats, assessment),
            files=[File(
                content=pdf_bytes,
                format="pdf",
                mime_type="application/pdf",
                name=f"boletim_{selected_property.id}.pdf",
            )],
        )

    except Exception as e:
        log_error(f"generate_property_boletim: {e}")
        return ToolResult(content=get_tool_result_text("analysis_tools", "generate_property_boletim", "error", error=e))