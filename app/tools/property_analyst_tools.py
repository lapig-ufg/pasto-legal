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
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural.
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
    """
    try:
        registered_properties = run_context.session_state['registered_properties']
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
    Realiza uma análise técnica detalhada do uso do solo e pastagem.
    """
    try:

        registered_properties = run_context.session_state["registered_properties"]
        selected_property = next((prop for prop in registered_properties if prop["car_code"] == ', '.join(car_codes)))
        selected_property = RuralProperty.model_validate(selected_property)

        new_pasture_stats: PastureStats = query_pasture_statistics(coords=selected_property.get_coords(), year=year)

        return ToolResult(content=str(new_pasture_stats))
    except Exception as e:
        return ToolResult(content=f"Erro na análise de pastagem: {str(e)}")