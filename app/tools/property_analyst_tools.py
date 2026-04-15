from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_selected_property_hook, validate_rate_limit_hook
from app.utils.scripts.gee_scripts import retrieve_feature_images, retrieve_feature_biomass_image, query_pasture_statistics
from app.utils.interfaces.property_stats import PastureStats, PropertyStats 
from app.utils.interfaces.property_record import PropertyRecord


@tool(tool_hooks=[validate_selected_property_hook, validate_rate_limit_hook])
def generate_property_image(run_context: RunContext, property_id: str) -> ToolResult:
    """
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural,
    incluindo a delimitação geográfica, com base nos últimos dois meses.

    Use apenas quando o usuário pedir para visualizar a propriedade.

    params:
        property_id (str): ID da propriedade no sistema.

    Return:
        ToolResult: Imagem PNG da visão aérea com delimitação geográfica.
    """
    try:
        registered_properties = run_context.session_state['registered_properties']
        selected_property = next((prop for prop in registered_properties if prop["id"] == property_id), None)
        selected_property = PropertyRecord.model_validate(selected_property)

        img = retrieve_feature_images(coords=selected_property.get_coords())[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"O contorno vermelho indica a delimitação geográfica da propriedade rural.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook, validate_rate_limit_hook])
def generate_biomass_image(run_context: RunContext, property_id: str, year: int = 2024) -> ToolResult:
    """
    Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade rural.

    params:
        property_id (str): ID da propriedade no sistema.
        year: O ano para a consulta dos dados (2000-2024).

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    try:
        registered_properties = run_context.session_state['registered_properties']
        selected_property = next((prop for prop in registered_properties if prop["id"] == property_id), None)
        selected_property = PropertyRecord.model_validate(selected_property)

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
def get_pasture_stats(run_context: RunContext, property_id: str, year: int = 2024):
    """
    Realiza uma análise técnica detalhada do uso do solo, com foco em pastagem, vigor vegetativo e biomassa
    para a propriedade selecionada no contexto (CAR).
    
    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Quantidade de biomassa disponível.
    - Classificação de uso do solo (LULC) incluindo: Silvicultura, Cana, Soja, Arroz, Café, Citrus, etc.
    - Idade da pastagem.

    params:
        property_id (str): ID da propriedade no sistema.
        year: O ano para a consulta dos dados (2000-2024).

    Return:
        Dicionário contendo a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor), biomassa total e a idade.
    """
    try:
        print(run_context.session_state, flush=True)
        properties_stats: list = run_context.session_state.get("properties_stats", [])
        property_stats = next((prop for prop in properties_stats if prop["id"] == property_id), None)
        new_property_stats = PropertyStats.model_validate(properties_stats) if property_stats else PropertyStats(id=property_id)
        
        for pasture_stats in new_property_stats.list_pasture_stats:
            if pasture_stats.year == year:
                return ToolResult(content=str(pasture_stats))
            
        registered_properties = run_context.session_state["registered_properties"]
        selected_property = next((prop for prop in registered_properties if prop["id"] == property_id))
        selected_property = PropertyRecord.model_validate(selected_property)

        new_pasture_stats: PastureStats = query_pasture_statistics(coords=selected_property.get_coords(), year=year)

        new_property_stats.list_pasture_stats.append(new_pasture_stats)

        if property_stats is not None:
            properties_stats.remove(property_stats)
        properties_stats.append(new_property_stats.model_dump())
        run_context.session_state["properties_stats"] = properties_stats

        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return ToolResult(content=str(e))