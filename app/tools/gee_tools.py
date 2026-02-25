import textwrap

from io import BytesIO

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext
from agno.media import Image

from app.hooks.tool_hooks import validate_car_hook
from app.utils.scripts.gee_scripts import retrieve_feature_images, retrieve_feature_biomass_image, ee_query_pasture

from app.utils.dummy_logger import error


# TODO: Escrever ferramenta para visualização da área de pastagem do usuário.
@tool(tool_hooks=[validate_car_hook])
def generate_property_image(run_context: RunContext) -> ToolResult:
    """
    Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural, 
    incluindo a delimitação geográfica do CAR.

    Esta ferramenta deve ser chamada quando:
    - O usuário quiser ver uma "foto", "imagem real" ou "visão aérea" da fazenda.
    - For solicitado o contorno da propriedade (CAR) sobreposto ao terreno natural.

    Return:
        ToolResult: Objeto contendo a imagem PNG da visão aérea e uma confirmação textual.
    """
    try:
        coordinates = run_context.session_state['car_selected']['geometry']['coordinates'][0][0]

        img = retrieve_feature_images(coordinates)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Aqui está a imagem de satélite da área. O contorno vermelho indica a zona de amortecimento de 5km.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_car_hook])
def generate_property_biomass_image(run_context: RunContext) -> ToolResult:
    """
    Gera um mapa geoespacial temático da biomassa (vegetação) sobre os limites da propriedade rural.
    
    Esta ferramenta deve ser acionada quando:
    - O usuário solicitar visualização espacial, mapas ou imagens da biomassa.
    - Termos como "ver a foto da biomassa" ou "ver distribuição de biomassa" forem utilizados.
    - For necessário complementar uma análise numérica de biomassa com uma evidência visual do terreno.

    A função utiliza automaticamente os dados geográficos do CAR selecionado no contexto da sessão para processar as imagens de satélite mais recentes.

    Return:
        ToolResult: Objeto contendo o mapa renderizado em formato PNG e uma mensagem de confirmação para o usuário.
    """
    try:
        coordinates = run_context.session_state['car_selected']['geometry']['coordinates'][0][0]

        img = retrieve_feature_biomass_image(coordinates)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Mapa de biomassa gerado. Legenda: Azul claro (Alta concentração) a Roxo escuro (Baixa concentração).",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_car_hook])
def query_pasture(run_context: RunContext) -> dict:
    """
    Realiza uma análise técnica detalhada do uso do solo, com foco em pastagem, vigor vegetativo e biomassa
    para a propriedade selecionada no contexto (CAR).
    
    Use esta ferramenta quando o usuário perguntar sobre:
    - Saúde ou qualidade da pastagem (degradação, vigor).
    - Quantidade de biomassa disponível.
    - Classificação de uso do solo (LULC) incluindo: Silvicultura, Cana, Soja, Arroz, Café, Citrus, etc.
    - Histórico ou idade da pastagem.

    Return:
        Dicionário contendo a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor), biomassa total e a idade.
    """
    try:
        coordinates = run_context.session_state['car_selected']['geometry']['coordinates'][0][0]

        query = ee_query_pasture(coordinates)
    
        return query
    except Exception as e:
        # TODO: Retornar menssagem de erro quando todos os erros forem mapeados dentro da função ee_query_pasture;
        error(f"Não foi possível concluir a função 'query_pasture': {e}")
        return ToolResult(content='Erro')