from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_selected_property_hook
from app.utils.scripts.gee_scripts import (
    retrieve_feature_images,
    retrieve_feature_biomass_image,
    retrieve_feature_soil_texture_image,
    query_pasture_statistics,
    query_topographic_stats,
    )
from app.utils.interfaces.property_stats import PastureStats, TopographicStats 
from app.utils.interfaces.property_record import RuralProperty


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
        registered_properties = run_context.session_state['registered_properties']
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ','.join(car_codes)), None)
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
def generate_biomass_image(run_context: RunContext, car_codes: list[str], year: int = 2024) -> ToolResult:
    """
    Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade rural.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.
        year (int): O ano para a consulta dos dados (2000-2024). O ano mais recente é 2024.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    try:
        registered_properties = run_context.session_state['registered_properties']
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        img = retrieve_feature_biomass_image(coords=selected_property.get_coords(), year=year)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Legenda: Azul claro (Alta concentração) a Roxo escuro (Baixa concentração).",
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
        registered_properties = run_context.session_state['registered_properties']
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)), None)
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
def get_pasture_stats(run_context: RunContext, car_codes: list[str], year: int = 2024):
    """
    Recupera estatísticas de bimoassa, vigor vegetativo, idade da pastagem e classificação de uso do solo.
   
    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Quantidade de biomassa disponível.
    - Classificação de uso do solo (LULC) incluindo: Silvicultura, Cana, Soja, Arroz, Café, Citrus, etc.
    - Idade da pastagem.

    params:
        car_codes (list[str]): Lista de códigos CAR da propriedade.
        year (str): O ano para a consulta dos dados (2000-2024). O ano mais recente é 2024.

    Return:
        Dicionário contendo a área de biomassa, vigor da pastagem, idade e uso e cobertura do solo.
    """
    try:
        #properties_stats = run_context.session_state.get("properties_stats", [])
        #property_stats = next((prop for prop in properties_stats if prop["id"] == property_id), None)
        #new_property_stats = PropertyStats.model_validate(properties_stats) if property_stats else PropertyStats(id=property_id)
        #
        #for pasture_stats in new_property_stats.list_pasture_stats:
        #    if pasture_stats.year == year:
        #        return ToolResult(content=str(pasture_stats))
            
        registered_properties = run_context.session_state["registered_properties"]
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        new_pasture_stats: PastureStats = query_pasture_statistics(coords=selected_property.get_coords(), year=year)

        #new_property_stats.list_pasture_stats.append(new_pasture_stats)

        #if property_stats is not None:
        #    properties_stats.remove(property_stats)
        #properties_stats.append(new_property_stats.model_dump())
        #run_context.session_state["properties_stats"] = properties_stats

        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
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
            
        registered_properties = run_context.session_state["registered_properties"]
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        new_topographic_stats: TopographicStats = query_topographic_stats(coords=selected_property.get_coords())

        #new_property_stats.list_pasture_stats.append(new_pasture_stats)

        #if property_stats is not None:
        #    properties_stats.remove(property_stats)
        #properties_stats.append(new_property_stats.model_dump())
        #run_context.session_state["properties_stats"] = properties_stats

        return ToolResult(content=str(new_topographic_stats))
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return ToolResult(content=str(e))