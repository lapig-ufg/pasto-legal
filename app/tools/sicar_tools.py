import json
import requests
import textwrap

from io import BytesIO

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image

from app.utils.scripts.sicar_scripts import (
    fetch_property_by_coordinates_remote, 
    fetch_property_by_coordinates_locally,
    fetch_property_by_car_remote,
    fetch_property_by_car_locally,
    )
from app.utils.scripts.image_scripts import get_mosaic
from app.utils.scripts.gee_scripts import retrieve_feature_images

@tool
def query_feature_by_coordinate(latitude: float, longitude: float, run_context: RunContext):
    """
    Busca imóveis no Cadastro Ambiental Rural (CAR) baseando-se nas coordenadas fornecidas.
    
    Use esta ferramenta quando o usuário fornecer uma localização (latitude/longitude) 
    e quiser verificar as propriedades rurais daquela região. Converta as coordenadas para
    graus decimais.
    
    Args:
        latitude (float): Latitude em graus decimais.
        longitude (float): Longitude em graus decimais.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    try:
        properties = fetch_property_by_coordinates_remote(latitude=latitude, longitude=longitude)
    except Exception:
        properties = fetch_property_by_coordinates_locally(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se as coordenadas estão corretas."
        )
    
    n_properties = len(properties)
    run_context.session_state['is_selecting_car'] = True

    coords = [prop.area_properties.coordinates[0] for prop in properties]
    imgs = retrieve_feature_images(coords)
    
    if n_properties == 1:
        prop = properties[0]

        run_context.session_state['car_candidate'] = prop
        run_context.session_state['car_selection_type'] = "SINGLE"

        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = (
            f"CAR {prop.code}, "
            f"Tamanho da área {round(prop.area_properties.total_area)} ha, "
            f"município de {prop.area_properties.municipality}."
        )

        return ToolResult(
            content=(
                "Informe ao usuário que a seguinte propriedade foi encontrada:\n\n"
                f"{result_text}\n\n"
                "Pergunte: 'É esta a propriedade correta?'"
            ),
            images=[Image(content=buffer.getvalue())]
            )
    
    elif n_properties > 1:
        run_context.session_state['car_all'] = properties
        run_context.session_state['car_selection_type'] = "MULTIPLE"

        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        options_text = []
        for i, p in enumerate(properties):
            options_text.append(
                f"- Opção {i + 1}: CAR {p.code}, "
                f"Tamanho da área {round(p.area_properties.total_area)} ha, "
                f"município de {p.area_properties.municipality}."
            )
        result_text = "\n".join(options_text)

        return ToolResult(
            content=(
                "Informe ao usuário que as seguintes propriedades foram encontradas:\n\n"
                f"{result_text}"
                "Pergunte: 'Qual destas é a propriedade correta?'"
            ),
            images=[Image(content=buffer.getvalue())]
            )

    
@tool
def query_feature_by_car(car: str, run_context: RunContext):
    """
    Busca imóveis no Cadastro Ambiental Rural (CAR) baseando-se nas coordenadas fornecidas.
    
    Use esta ferramenta quando o usuário fornecer um valor de CAR válido.
    
    Args:
        car (str): Valor de Cadastro Ambiental Rural (CAR) válido.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    try:
        prop = fetch_property_by_car_remote(car=car)
    except Exception:
        prop = fetch_property_by_car_locally(car=car)

    if not prop:
        return ToolResult(
            content=(
                "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                "Peça que tente novamente e verificar se as coordenadas estão corretas."
            )
        )

    img = retrieve_feature_images(prop.area_properties.coordinates)[0]

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    
    run_context.session_state['car_candidate'] = prop
    run_context.session_state['is_selecting_car'] = True
    run_context.session_state['car_selection_type'] = "SINGLE"

    result_text = (
        f"- CAR {prop.code}, "
        f"Tamanho da área {round(prop.area_properties.total_area)} ha, "
        f"município de {prop.area_properties.municipality}.\n"
    )

    return ToolResult(
        content=(
            "A seguinte propriedade foi encontrada:\n\n"
            f"{result_text}"
            "É a propriedade correta?"
        ),
        images=[Image(content=buffer.getvalue())]
        )


@tool
def select_car_from_list(selection: int, run_context: RunContext):
    """
    Seleciona uma propriedade específica quando a busca retorna múltiplos resultados.
    
    Use esta ferramenta APENAS quando o usuário fornecer um número correspondente a uma das opções apresentadas anteriormente.

    Args:
        selection (int): O número da opção escolhida pelo usuário (ex: 1, 2, 3...).
    """
    try:
        features = run_context.session_state.get('car_all', [])
        
        if not features:
            return ToolResult(content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro.")

        if selection < 1 or selection > len(features):
            return ToolResult(content=f"Seleção inválida. Escolha um número válido entre 1 e {len(features)}.")

        selected_feature = features[selection - 1]
        selected_feature['properties']['area'] = round(selected_feature['properties']['area'])
        run_context.session_state['car_selected'] = selected_feature

        run_context.session_state['car_all'] = []
        run_context.session_state['is_selecting_car'] = False
        run_context.session_state['car_selection_type'] = None

        return ToolResult(content=(
                "Informe ao usuário que a propriedade foi selecionada corretamente. ✅\n"
                "Pergunte ao usuário como ele deseja prosseguir. Algumas opções são:\n"
                "- 🌱 *Análise de pastagem*\n"
                "- 🗺️ *Uso e cobertura da terra*\n"
                "- 📊 *Visualização de biomassa*"
            )
        )
    except Exception as e:
        return ToolResult(content=f"[ERRO] Falha ao selecionar: {str(e)}")


@tool
def confirm_car_selection(run_context: RunContext):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.
    
    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").
    """
    candidate = run_context.session_state.get('car_candidate')
    
    if not candidate:
        return ToolResult(content="Não há propriedade pendente de confirmação. Realize uma busca primeiro.")

    run_context.session_state['car_selected'] = candidate

    run_context.session_state['car_candidate'] = None
    run_context.session_state['is_selecting_car'] = False
    run_context.session_state['car_selection_type'] = None

    return ToolResult(content=(
                "Informe ao usuário que a propriedade foi selecionada corretamente. ✅\n"
                "Pergunte ao usuário como ele deseja prosseguir. Algumas opções são:\n"
                "- 🌱 *Análise de pastagem*\n"
                "- 🗺️ *Uso e cobertura da terra*\n"
                "- 📊 *Visualização de biomassa*"
            )
        )


@tool
def reject_car_selection(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    run_context.session_state['car_all'] = []
    run_context.session_state['car_candidate'] = None
    run_context.session_state['is_selecting_car'] = False
    run_context.session_state['car_selection_type'] = None

    return ToolResult(
        content=(
            "Peça desculpas por não ter encontrado a propriedade correta.\n"
            "Peça ao usuário que verifica se as coordenadas ou car estão corretos."
        )
    )