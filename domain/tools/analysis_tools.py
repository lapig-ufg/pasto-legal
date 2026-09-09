import datetime

from io import BytesIO

import PIL

from semente import tool
from semente import ToolResult
from semente.context import Context as RunContext
from semente import File, Image, Video
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description
from semente.hooks.tool_hooks import validate_selected_property_hook
from domain.services.video import gif_bytes_to_mp4_bytes
from domain.services.geospatial.image import append_continuous_colorbar, draw_corner_label
from domain.services.geospatial.gee import (
    BIOMASS_VIDEO_PALETTE,
    retrieve_feature_images,
    retrieve_mapbiomas_biomass_image,
    retrieve_t2g_biomass_image,
    retrieve_t2g_biomass_video,
    retrieve_pasture_vigor_image,
    retrieve_feature_soil_texture_image,
    query_pasture_statistics,
    query_topographic_stats,
    )
from domain.services.geospatial.pasture_classification import classify_pasture_on_the_fly
from domain.services.boletim_scripts import build_boletim_chat_summary, build_boletim_story
from domain.services.pdf_scripts import render_document
from domain.schemas.property_stats import PastureStats, PropertyStats, TopographicStats
from domain.utils.feature_utils import resolve_feature
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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        img = retrieve_feature_images(coords=selected_property.get_coords())[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        log_debug(f"generate_property_image: imagem gerada ({selected_property.id})")
        return ToolResult(
            content="O contorno vermelho indica a delimitação geográfica da propriedade rural.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_property_image: {e}")
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "generate_biomass_image"))
def generate_biomass_image(run_context: RunContext, feature_id: str) -> ToolResult:
    """
    Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade rural.

    params:
        feature_id (str): Identificador (id) da feição registrada.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    log_debug(f"generate_biomass_image: feature_id={feature_id}")
    try:
        selected_property = resolve_feature(run_context, feature_id)
        if selected_property is None:
            log_warning(f"Feição não encontrada: {feature_id}")
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        today = datetime.date.today()

        result = retrieve_t2g_biomass_image(selected_property.get_coords(), today.month, today.year)

        if result is not None:
            biomass_img, _target_year, _target_month = result

            buffer = BytesIO()
            biomass_img.save(buffer, format="PNG")

            log_debug(f"generate_biomass_image: mapa t2g gerado ({selected_property.id}, {_target_month}/{_target_year})")
            return ToolResult(
                content=(f"Legenda: Acumulado de biomassa no mês de referência. Azul claro (Alta concentração) a Roxo escuro (Baixa concentração). Data referência: mês {_target_month}, ano {_target_year}"),
                images=[Image(content=buffer.getvalue())]
            )

        img = retrieve_mapbiomas_biomass_image(selected_property.get_coords(), year=2024)

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        log_debug(f"generate_biomass_image: mapa mapbiomas gerado ({selected_property.id})")
        return ToolResult(
            content=("Legenda: Acumulado de biomassa no ano de referência. Azul claro (Alta concentração) a Roxo escuro (Baixa concentração). Data referência: ano 2024"),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_biomass_image: {e}")
        return ToolResult(content=str(e))


def _overlay_fixed_colorbar(
    gif_bytes: bytes,
    vmin: float,
    vmax: float,
    title: str,
    frame_dates: list[str] | None = None,
) -> bytes:
    """
    Sobrepõe uma barra de cores fixa (escala global) em todos os frames de um GIF,
    e opcionalmente um rótulo de data (canto superior esquerdo) por frame.

    Args:
        gif_bytes (bytes): Conteúdo do GIF animado de entrada.
        vmin (float): Valor mínimo global da escala (ton/ha).
        vmax (float): Valor máximo global da escala (ton/ha).
        title (str): Título exibido acima da imagem; a barra de cores abaixo
            indica os valores mínimo, intermediário e máximo, com a unidade
            (ton/ha) no rótulo máximo.
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
                    vmin=round(vmin),
                    vmax=round(vmax),
                    unit="ton/ha",
                    palette=BIOMASS_VIDEO_PALETTE,
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


@tool(tool_hooks=[validate_selected_property_hook])
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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        result = retrieve_t2g_biomass_video(
            coords=selected_property.get_coords(),
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )

        if result is None:
            log_warning(f"generate_biomass_video: sem dados UGPP suficientes ({selected_property.id})")
            return ToolResult(
                content=(
                    "Não há dados de biomassa suficientes (pelo menos dois meses) para gerar o vídeo "
                    f"no período de {start_month}/{start_year} a {end_month}/{end_year}. "
                    "Informe que a série T2G pode não cobrir a região ou o período solicitado e "
                    "sugira um período mais recente ou um mapa de biomassa do mês atual."
                )
            )

        gif_bytes, effective_start, effective_end, frame_months, global_min, global_max = result

        frame_dates = [f"{acc_month:02d}/{acc_year}" for acc_year, acc_month in frame_months]
        gif_bytes = _overlay_fixed_colorbar(
            gif_bytes,
            vmin=global_min,
            vmax=global_max,
            title="Biomassa (T2G)",
            frame_dates=frame_dates,
        )
        mp4_bytes = gif_bytes_to_mp4_bytes(gif_bytes)

        log_debug(
            f"generate_biomass_video: vídeo gerado ({selected_property.id}, "
            f"{effective_start[1]}/{effective_start[0]} - {effective_end[1]}/{effective_end[0]})"
        )
        return ToolResult(
            content=(
                f"Vídeo da evolução mensal da biomassa (ton/ha) de {effective_start[1]}/{effective_start[0]} "
                f"a {effective_end[1]}/{effective_end[0]}, sobre a imagem de satélite e com o contorno "
                "da propriedade. Cada frame é o acumulado do mês indicado no canto superior esquerdo "
                "(formato MM/AAAA), com barra de cores de escala fixa entre os frames: Roxo escuro "
                f"(Baixa concentração) a Azul claro (Alta concentração), variando de {round(global_min)} "
                f"a {round(global_max)} ton/ha. Meses sem dados disponíveis foram omitidos."
            ),
            videos=[Video(content=mp4_bytes, mime_type="video/mp4", format="mp4")],
        )

    except Exception as e:
        log_error(f"generate_biomass_video: {e}")
        return ToolResult(content=str(e))


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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        roi = ee.Geometry.MultiPolygon(selected_property.get_coords())
        result = classify_pasture_on_the_fly(roi=roi, feature_id=selected_property.id)

        buffer = BytesIO()
        result["imagem"].save(buffer, format="PNG")

        log_debug(f"generate_pasture_classification_image: classificação gerada ({selected_property.id}, {result['area_pasto_ha']} ha)")
        return ToolResult(
            content=(
                f"Área de pastagem classificada (ano {result['pred_year']}): "
                f"{result['area_pasto_ha']} hectares. Legenda: Verde (Pastagem)."
            ),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_pasture_classification_image: {e}")
        return ToolResult(content=str(e))


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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        img = retrieve_feature_soil_texture_image(coords=selected_property.get_coords())

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        log_debug(f"generate_soil_texture_image: mapa de solo gerado ({selected_property.id})")
        return ToolResult(
            content="Legenda: Afloramento (#707070), Muito Argiloso (#9B0F06), Argila (#BFA28C), Siltoso (#D8F467), Arenoso (#FFD400) e Médio (#F0CFA1).",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        log_error(f"generate_soil_texture_image: {e}")
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook], description=get_tool_description("analysis_tools", "get_pasture_stats"))
def get_pasture_stats(run_context: RunContext, feature_id: str):
    """
    Recupera estatísticas de bimoassa, vigor vegetativo, idade da pastagem e classificação de uso do solo mais recentes.

    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Quantidade de biomassa disponível.
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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        today = datetime.date.today()

        new_pasture_stats: PastureStats = query_pasture_statistics(
            coords=selected_property.get_coords(),
            month=today.month,
            year=today.year
        )

        log_debug(f"get_pasture_stats: stats recuperadas ({selected_property.id})")
        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        log_error(f"get_pasture_stats: {e}")
        return ToolResult(content=str(e))


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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        new_topographic_stats: TopographicStats = query_topographic_stats(coords=selected_property.get_coords())

        log_debug(f"get_topographic_stats: stats recuperadas ({selected_property.id})")
        return ToolResult(content=str(new_topographic_stats))
    except Exception as e:
        log_error(f"get_topographic_stats: {e}")
        return ToolResult(content=str(e))


def _pil_to_png_bytes(img) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


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
    classificação de pastagem, biomassa, vigor e tipos de solo — com os mapas
    correspondentes, pronto para compartilhar com agrônomos ou parceiros.

    IMPORTANTE: a biomassa é calculada para o mês/ano atual; idade, vigor e uso do
    solo (LULC) refletem o ano mais recente disponível no MapBiomas (2024). Avise o
    usuário sobre essa defasagem ao entregar o boletim.

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
            return ToolResult(content=f"Feição não encontrada: {feature_id}")

        coords = selected_property.get_coords()
        today = datetime.date.today()

        pasture_stats = query_pasture_statistics(coords=coords, month=today.month, year=today.year)
        stats = PropertyStats(car_code=selected_property.id, list_pasture_stats=[pasture_stats])

        location_image = retrieve_feature_images(coords)[0]

        roi = ee.Geometry.MultiPolygon(coords)
        pasture_result = classify_pasture_on_the_fly(roi=roi, feature_id=selected_property.id)
        pasture_map_image = pasture_result["imagem"]

        def _fetch_biomass_image():
            result = retrieve_t2g_biomass_image(coords, today.month, today.year)
            if result is not None:
                biomass_img, _target_year, _target_month = result
                return biomass_img
            return retrieve_mapbiomas_biomass_image(coords, year=2024)

        biomass_map_image = _safe_fetch_image("mapa de biomassa", _fetch_biomass_image)
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
        )
        pdf_bytes = render_document(story)

        log_debug(f"generate_property_boletim: boletim gerado ({selected_property.id})")
        return ToolResult(
            content=build_boletim_chat_summary(selected_property, pasture_stats),
            files=[File(
                content=pdf_bytes,
                format="pdf",
                mime_type="application/pdf",
                name=f"boletim_{selected_property.id}.pdf",
            )],
        )

    except Exception as e:
        log_error(f"generate_property_boletim: {e}")
        return ToolResult(content=str(e))