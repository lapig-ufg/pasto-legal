from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_car_hook
from app.utils.scripts.gee_scripts import retrieve_feature_images, retrieve_feature_biomass_image, ee_query_pasture
from app.utils.dummy_logger import error


# TODO: Escrever ferramenta para visualização da área de pastagem do usuário.
# TODO: Deveria ter um buffer para as laterais da imagem não encostarem na região do poligono.
# TODO: A imagem do satelite deveria estar inteira, e não cliped na região de interesse.
# TODO: DUVIDA - Faz sentido manter para caso o usuário queira uma imagem da propriedade ou é melhor armazenas a imagem?
@tool(tool_hooks=[validate_car_hook], requires_confirmation=False)
def generate_property_image(run_context: RunContext) -> ToolResult:
    """
    Gera uma imagem de satélite da propriedade rural baseada nos dados do CAR do usuário
    armazenados na sessão. Esta função não requer parâmetros, pois recupera 
    automaticamente a geometria da fazenda do estado atual da conversa.

    Esta função deve ser chamada quando:
    - O usuário pedir para "ver", "mostrar" ou "gerar mapa" da fazenda/propriedade.
    - O usuário quiser visualizar o contorno da área (CAR) sobreposto ao terreno.

    Return:
        Retorna um objeto ToolResult contendo a imagem da propriedade do usuário em formato PNG e uma breve descrição.
    """
    try:
        img_pil = retrieve_feature_images(run_context.session_state['car']['features'][0])

        buffer = BytesIO()
        img_pil.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Aqui está a imagem de satélite da área. O contorno vermelho indica a zona de amortecimento de 5km.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_car_hook])
def query_pasture(run_context: RunContext) -> dict:
    """
    Calcula a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor),
    biomassa total e a idade baseada nos dados do CAR do usuário armazenados na sessão. Esta função não
    requer parâmetros, pois recupera automaticamente a geometria da fazenda do estado atual da conversa.

    Return:
        Dicionário contendo a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor), biomassa total e a idade.
    """
    try:
        coordinates = run_context.session_state['car_selected']['geometry']['coordinates'][0][0]

        #imgs = retrieve_feature_biomass_image(coordinates)

        #buffer = BytesIO()
        #imgs.save(buffer, format="PNG")

        result = ee_query_pasture(coordinates)
    
        # TODO: Retornar imagem com biomassa?
        return result
    except Exception as e:
        # TODO: Retornar menssagem de erro quando todos os erros forem mapeados dentro da função ee_query_pasture;
        error(f"Não foi possível concluir a função 'query_pasture': {e}")
        return ToolResult(content='Erro')