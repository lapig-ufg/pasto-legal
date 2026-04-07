from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_selected_property_hook
from app.utils.scripts.gee_scripts import retrieve_feature_images, retrieve_feature_biomass_image, ee_query_pasture
from app.utils.interfaces.ee_data_interfaces import BiomassData, VigorData, AgeData, LULCClassData


# TODO: Escrever ferramenta para visualização da área de pastagem do usuário.
@tool(tool_hooks=[validate_selected_property_hook])
def generate_property_image(run_context: RunContext) -> ToolResult:
    """
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural, incluindo a delimitação geográfica.

    Esta ferramenta deve ser chamada quando:
    - O usuário quiser ver uma "foto", "imagem real" ou "visão aérea" da fazenda.
    - For solicitado o contorno da propriedade (CAR) sobreposto ao terreno natural.

    Return:
        ToolResult: Imagem PNG da visão aérea com delimitação geográfica.
    """
    try:
        coords = run_context.session_state['selected_property']['spatial_features']['coordinates']

        img = retrieve_feature_images(coords=coords)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"O contorno vermelho indica a delimitação geográfica da propriedade rural.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_selected_property_hook])
def generate_biomass_image(run_context: RunContext, car: str = None, year: int = None) -> ToolResult:
    """
    Gera um mapa geoespacial temático da biomassa (matéria seca) sobre os limites da propriedade rural.

    params:
        car (str): Código de Cadastro Ambiental Rural (CAR), `None` para a propriedade selecionada no sistema.
        year (int): Ano para a consulta dos dados, `None` para o ano atual.

    Return:
        ToolResult: Mapa renderizado em formato PNG.
    """
    try:
        if car is None:
            _property = run_context.session_state['selected_property']
        else:
            all_properties = run_context.session_state['all_properties']
            _property = [prop for prop in all_properties if prop["car_code"] == car][0]
            
        coords = _property['spatial_features']['coordinates']

        img = retrieve_feature_biomass_image(coords=coords)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Legenda: Azul claro (Alta concentração) a Roxo escuro (Baixa concentração).",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=str(e))


@tool
def query_pasture_biomass(run_context: RunContext, car: str = None, year: int = None):
    """
    Busca os dados de biomassa de pastagem (matéria seca) de uma propriedade rural.

    Args:
        car: O código Cadastro Ambiental Rural (CAR) da propriedade, `None` para a propriedade selecionada no sistema.
        year: O ano para a consulta dos dados, `None` para o ano atual. 
    """
    try:
        if car is None:
            _property = run_context.session_state['selected_property']
        else:
            all_properties = run_context.session_state['all_properties']
            _property = [prop for prop in all_properties if prop["car_code"] == car][0]

        if _property.get("data", None) is None:
            _property["data"] = {}

        if _property["data"].get("pasture_data", None) is None:
            _property["data"]["pasture_data"] = {}

        if _property["data"]["pasture_data"].get(year, None) is None:
            _property["data"]["pasture_data"][year] = {}

            coords = _property["spatial_features"]["coordinates"]

            query = ee_query_pasture(coords=coords)

            _property["data"]["pasture_data"][year] = query.model_dump()

        return ToolResult(content=str(BiomassData.model_validate(_property["data"]["pasture_data"][year]["biomass"])))
    except Exception as e:
        return ToolResult(content=str(e))


@tool
def query_pasture_vigor(run_context: RunContext, car: str = None, year: int = None):
    """
    Busca os dados de vigor vegetativo de pastagem de uma propriedade rural.

    Args:
        car: O código Cadastro Ambiental Rural (CAR) da propriedade, `None` para a propriedade selecionada no sistema.
        year: O ano para a consulta dos dados, `None` para o ano atual. 
    """
    try:
        if car is None:
            _property = run_context.session_state['selected_property']
        else:
            all_properties = run_context.session_state['all_properties']
            _property = [prop for prop in all_properties if prop["car_code"] == car][0]

        if _property.get("data", None) is None:
            _property["data"] = {}

        if _property["data"].get("pasture_data", None) is None:
            _property["data"]["pasture_data"] = {}

        if _property["data"]["pasture_data"].get(year, None) is None:
            _property["data"]["pasture_data"][year] = {}

            coords = _property["spatial_features"]["coordinates"]

            query = ee_query_pasture(coords=coords)

            _property["data"]["pasture_data"][year] = query.model_dump()

        vigor_list = _property["data"]["pasture_data"][year]["vigor"]

        return ToolResult(content=str([VigorData.model_validate(vigor) for vigor in vigor_list]))
    except Exception as e:
        return ToolResult(content=str(e))


@tool
def query_pasture_age(run_context: RunContext, car: str = None, year: int = None):
    """
    Busca os dados de idade da pastagem de uma propriedade rural.

    Args:
        car: O código Cadastro Ambiental Rural (CAR) da propriedade, `None` para a propriedade selecionada no sistema.
        year: O ano para a consulta dos dados, `None` para o ano atual. 
    """
    try:
        if car is None:
            _property = run_context.session_state['selected_property']
        else:
            all_properties = run_context.session_state['all_properties']
            _property = [prop for prop in all_properties if prop["car_code"] == car][0]

        if _property.get("data", None) is None:
            _property["data"] = {}

        if _property["data"].get("pasture_data", None) is None:
            _property["data"]["pasture_data"] = {}

        if _property["data"]["pasture_data"].get(year, None) is None:
            _property["data"]["pasture_data"][year] = {}

            coords = _property["spatial_features"]["coordinates"]

            query = ee_query_pasture(coords=coords)

            _property["data"]["pasture_data"][year] = query.model_dump()

        age_list = _property["data"]["pasture_data"][year]["age"]

        return ToolResult(content=str([AgeData.model_validate(age) for age in age_list]))
    except Exception as e:
        return ToolResult(content=str(e))


@tool
def query_pasture_lulc(run_context: RunContext, car: str = None, year: int = None):
    """
    Busca os dados de uso e cobertura da terra de uma propriedade rural.

    Args:
        car: O código Cadastro Ambiental Rural (CAR) da propriedade, `None` para a propriedade selecionada no sistema.
        year: O ano para a consulta dos dados, `None` para o ano atual. 
    """
    try:
        if car is None:
            _property = run_context.session_state['selected_property']
        else:
            all_properties = run_context.session_state['all_properties']
            _property = [prop for prop in all_properties if prop["car_code"] == car][0]

        if _property.get("data", None) is None:
            _property["data"] = {}

        if _property["data"].get("pasture_data", None) is None:
            _property["data"]["pasture_data"] = {}

        if _property["data"]["pasture_data"].get(year, None) is None:
            _property["data"]["pasture_data"][year] = {}

            coords = _property["spatial_features"]["coordinates"]

            query = ee_query_pasture(coords=coords)

            _property["data"]["pasture_data"][year] = query.model_dump()

        lulc_class_list = _property["data"]["pasture_data"][year]["lulc_class"]
        
        return ToolResult(content=str([LULCClassData.model_validate(lulc_class) for lulc_class in lulc_class_list]))
    except Exception as e:
        return ToolResult(content=str(e))