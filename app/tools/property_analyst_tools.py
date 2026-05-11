from io import BytesIO
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_selected_property_hook, validate_rate_limit_hook
from app.utils.scripts.gee_scripts import retrieve_feature_images, retrieve_feature_biomass_image, query_pasture_statistics
from app.utils.interfaces.property_stats import PastureStats
from app.utils.interfaces.property_record import RuralProperty


@tool(tool_hooks=[validate_selected_property_hook, validate_rate_limit_hook])
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
            content="O contorno vermelho indica a delimitação geográfica da propriedade rural.",
            images=[Image(content=buffer.getvalue())]
        )
    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook, validate_rate_limit_hook])
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
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)), None)
        selected_property = RuralProperty.model_validate(selected_property)

        img = retrieve_feature_biomass_image(coords=selected_property.get_coords(), year=year)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content="Legenda: Azul claro (Alta concentração) a Roxo escuro (Baixa concentração).",
            images=[Image(content=buffer.getvalue())]
        )
    except Exception as e:
        return ToolResult(content=f"Erro ao gerar mapa de biomassa: {str(e)}")


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

        registered_properties = run_context.session_state["registered_properties"]
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        new_pasture_stats: PastureStats = query_pasture_statistics(coords=selected_property.get_coords(), year=year)

        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        return ToolResult(content=f"Erro na análise de pastagem: {str(e)}")