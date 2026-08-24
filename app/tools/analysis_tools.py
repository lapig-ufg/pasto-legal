import datetime

from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import File, Image
from agno.utils.log import log_error

from app.hooks.tool_hooks import validate_selected_property_hook
from app.services.geospatial.gee import (
    retrieve_feature_images,
    retrieve_mapbiomas_biomass_image,
    retrieve_t2g_biomass_image,
    retrieve_pasture_vigor_image,
    retrieve_feature_soil_texture_image,
    query_pasture_statistics,
    query_topographic_stats,
    )
from app.services.geospatial.pasture_classification import classify_pasture_on_the_fly
from app.services.boletim_scripts import build_boletim_chat_summary, build_boletim_story
from app.services.pdf_scripts import render_document
from app.schemas.property_stats import PastureStats, PropertyStats, TopographicStats
from app.schemas.rural_property import RuralProperty
import ee


@tool(tool_hooks=[validate_selected_property_hook])
def generate_property_image(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural,
    incluindo a delimitação geográfica, com base nos últimos dois meses.

    Use apenas quando o usuário pedir para visualizar a propriedade.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Imagem PNG da visão aérea com delimitação geográfica.
    """
    try:
        all_properties = run_context.session_state['all_properties']
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ','.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        img = retrieve_feature_images(coords=selected_property.get_coords())[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"O contorno vermelho indica a delimitação geográfica da propriedade rural.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook])
def generate_biomass_image(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade rural.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    try:
        all_properties = run_context.session_state['all_properties']
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)   

        today = datetime.date.today()

        result = retrieve_t2g_biomass_image(selected_property.get_coords(), today.month, today.year, today.day)

        if result is not None:
            biomass_img, _target_year, _target_month = result

            buffer = BytesIO()
            biomass_img.save(buffer, format="PNG")

            return ToolResult(
                content=(f"Legenda: Acumulado de biomassa no mês de referência. Azul claro (Alta concentração) a Roxo escuro (Baixa concentração). Data referência: mês {_target_month}, ano {_target_year}"),
                images=[Image(content=buffer.getvalue())]
            )

        img = retrieve_mapbiomas_biomass_image(selected_property.get_coords(), year=2024)

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        return ToolResult(
            content=(f"Legenda: Acumulado de biomassa no ano de referência. Azul claro (Alta concentração) a Roxo escuro (Baixa concentração). Data referência: ano 2024"),
            images=[Image(content=buffer.getvalue())]
        )
                
    except Exception as e:
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook])
def generate_pasture_classification_image(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Gera o mapa de classificação de pastagem (pasto x não-pasto) da propriedade rural,
    calculado sob demanda ("on-the-fly") para o ano mais recente disponível.

    Diferente de `get_pasture_stats` (que usa o mapeamento oficial do MapBiomas, sempre
    com pelo menos um ano de atraso), esta ferramenta classifica a propriedade em tempo real
    usando o ano de satélite mais recente disponível, útil quando o usuário quer o mapeamento
    de uso do solo mais atualizado possível.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Mapa em PNG (verde = pastagem) e a área de pastagem em hectares.
    """
    try:
        all_properties = run_context.session_state['all_properties']
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        roi = ee.Geometry.MultiPolygon(selected_property.get_coords())
        result = classify_pasture_on_the_fly(roi=roi, car_code=selected_property.car_code)

        buffer = BytesIO()
        result["imagem"].save(buffer, format="PNG")

        return ToolResult(
            content=(
                f"Área de pastagem classificada (ano {result['pred_year']}): "
                f"{result['area_pasto_ha']} hectares. Legenda: Verde (Pastagem)."
            ),
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook])
def generate_soil_texture_image(run_context: RunContext, car_codes: list[str]) -> ToolResult:
    """
    Gera um mapa temático da textura do solo sobre os limites da propriedade rural na profundidade de 0 a 30cm.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    try:
        all_properties = run_context.session_state['all_properties']
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        img = retrieve_feature_soil_texture_image(coords=selected_property.get_coords())

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Legenda: Afloramento (#707070), Muito Argiloso (#9B0F06), Argila (#BFA28C), Siltoso (#D8F467), Arenoso (#FFD400) e Médio (#F0CFA1).",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=str(e))


@tool(tool_hooks=[validate_selected_property_hook])
def get_pasture_stats(run_context: RunContext, car_codes: list[str]):
    """
    Recupera estatísticas de bimoassa, vigor vegetativo, idade da pastagem e classificação de uso do solo mais recentes.
   
    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Quantidade de biomassa disponível.
    - Classificação de uso do solo (LULC) incluindo: Silvicultura, Cana, Soja, Arroz, Café, Citrus, etc.
    - Idade da pastagem.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        Dicionário contendo a área de biomassa, vigor da pastagem, idade e uso e cobertura do solo.
    """
    try:
        all_properties = run_context.session_state["all_properties"]
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        today = datetime.date.today()

        new_pasture_stats: PastureStats = query_pasture_statistics(
            coords=selected_property.get_coords(),
            year=today.year,
            month=today.month,
            day=today.day
        )

        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        log_error(f"ERROR: {e}")
        return ToolResult(content=str(e))
    

@tool(tool_hooks=[validate_selected_property_hook])
def get_topographic_stats(run_context: RunContext, car_codes: list[str]):
    """
    Recupera estatísticas de topografia da propriedade (altimetria e declividade).

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        Dicionário contendo as informações de altimetria e declividade.
    """
    try:
        #properties_stats = run_context.session_state.get("properties_stats", [])
        #property_stats = next((prop for prop in properties_stats if prop["id"] == property_id), None)
        #new_property_stats = PropertyStats.model_validate(properties_stats) if property_stats else PropertyStats(id=property_id)
        #
        #for pasture_stats in new_property_stats.list_pasture_stats:
        #    if pasture_stats.year == year:
        #        return ToolResult(content=str(pasture_stats))
            
        all_properties = run_context.session_state["all_properties"]
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        new_topographic_stats: TopographicStats = query_topographic_stats(coords=selected_property.get_coords())

        #new_property_stats.list_pasture_stats.append(new_pasture_stats)

        #if property_stats is not None:
        #    properties_stats.remove(property_stats)
        #properties_stats.append(new_property_stats.model_dump())
        #run_context.session_state["properties_stats"] = properties_stats

        return ToolResult(content=str(new_topographic_stats))
    except Exception as e:
        log_error(f"ERROR: {e}")
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


@tool(tool_hooks=[validate_selected_property_hook])
def generate_property_boletim(run_context: RunContext, car_codes: list[str]) -> ToolResult:
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
        car_codes (list[str]): Lista de códigos CAR da propriedade.

    Return:
        ToolResult: Arquivo PDF do boletim com dados e mapas reais da propriedade.
    """
    try:
        all_properties = run_context.session_state['all_properties']
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        coords = selected_property.get_coords()
        today = datetime.date.today()

        pasture_stats = query_pasture_statistics(coords=coords, year=today.year, month=today.month, day=today.day)
        stats = PropertyStats(car_code=selected_property.car_code, list_pasture_stats=[pasture_stats])

        location_image = retrieve_feature_images(coords)[0]

        roi = ee.Geometry.MultiPolygon(coords)
        pasture_result = classify_pasture_on_the_fly(roi=roi, car_code=selected_property.car_code)
        pasture_map_image = pasture_result["imagem"]

        def _fetch_biomass_image():
            result = retrieve_t2g_biomass_image(coords, today.month, today.year, today.day)
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

        return ToolResult(
            content=build_boletim_chat_summary(selected_property, pasture_stats),
            files=[File(
                content=pdf_bytes,
                format="pdf",
                mime_type="application/pdf",
                name=f"boletim_{selected_property.car_code}.pdf",
            )],
        )

    except Exception as e:
        return ToolResult(content=str(e))