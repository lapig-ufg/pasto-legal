import re

from io import BytesIO
from typing import List, Tuple

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image

from app.utils.scripts.sicar_scripts import (
    fetch_property_by_coordinates_remote, 
    fetch_property_by_coordinates_locally,
    fetch_property_by_car_remote,
    fetch_property_by_car_locally,
    fetch_coordinates_by_url,
    clean_car_code
    )
from app.utils.scripts.image_scripts import get_mosaic
from app.utils.scripts.gee_scripts import retrieve_feature_images


# TODO: Se o usuário informar as coordenadas de uma propriedade que já existe no sistema, validar se a propriedade existe por meio do CAR. Se existir então retornar menssagem que já existe.
# TODO: Se o usuário informar uma URL de coordenadas de uma propriedade que já existe no sistema, validar se a propriedade existe por meio do CAR. Se existir então retornar menssagem que já existe.

@tool(stop_after_tool_call=True)
def register_feature_by_coordinate(latitude: float, longitude: float, run_context: RunContext):
    """
    Registra uma nova propriedade rural baseando-se nas coordenadas fornecidas.
    
    Use esta ferramenta quando o usuário fornecer coordenadas geográficas (latitude/longitude).
    
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

    imgs = retrieve_feature_images([p["spatial_features"]["coordinates"][0] for p in properties])

    run_context.session_state["candidate_properties"] = properties
    
    if len(properties) == 1:
        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = (
            f"  > Identificador CAR: {properties[0]["car_code"]}, "
            f"Tamanho da área: {round(properties[0]["spatial_features"]["total_area"])} ha, "
            f"Município: {properties[0]["spatial_features"]["municipality"]}."
        )

        return ToolResult(
            content=(f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}"),
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        options_text = []
        for i, p in enumerate(properties):
            options_text.append(
                f"  > Opção {i + 1} - Identificador CAR {p["car_code"]}, "
                f"Tamanho da área {round(p["spatial_features"]["total_area"])} ha, "
                f"município de {p["spatial_features"]["municipality"]}."
            )
        result_text = "\n".join(options_text)

        return ToolResult(
            content=(f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}"),
            images=[Image(content=buffer.getvalue())]
            )

    
def register_feature_by_car(run_context: RunContext, car_codes: List[str], name: str = None):
    """
    Registra uma nova propriedade rural baseando-se nas coordenadas fornecidas.
    
    Use esta ferramenta quando o usuário fornecer um valor de CAR ainda não registrado no sistema.
    
    Args:
        cars (List[str]): Código de Cadastro Ambiental Rural (CAR) padrão SICAR.
        name (str): Nome da propriedade. `None` caso não seja informado.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    clean_car_codes = []

    for car_code in car_codes:
        if (new_car_code := clean_car_code(car_code)) is None:
            return  ToolResult(
                content=(
                    "Peça desculpas e informe que o sistema aceita exclusivamente o **CAR Federal** (padrão SICAR).\n"
                    "Explique que o padrão exige: 2 letras do Estado, seguidas por 7 números, e terminando com 32 caracteres."
                )
            )
        
    try:
        properties = fetch_property_by_car_remote(car=formatted_car)
    except Exception:
        properties = fetch_property_by_car_locally(car=formatted_car)

    if not properties:
        return ToolResult(
            content=(
                "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                "Peça que tente novamente e verificar se as coordenadas estão corretas."
            )
        )

    img = retrieve_feature_images(properties[0]["spatial_features"]["coordinates"])[0]

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    
    run_context.session_state['candidate_properties'] = properties

    result_text = (
        f"  > Identificador CAR: {properties[0]["car_code"]}, "
        f"Tamanho da área: {round(properties[0]["spatial_features"]["total_area"])} ha, "
        f"Município: {properties[0]["spatial_features"]["municipality"]}.\n"
    )

    return ToolResult(
        content=f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}",
        images=[Image(content=buffer.getvalue())]
        )


@tool(stop_after_tool_call=True)
def register_feature_by_url(url: str, run_context: RunContext) -> ToolResult:
    """
    Registra uma nova propriedade rural baseando-se na URL de compartilhamento do Google Maps.
    
    Use esta ferramenta quando o usuário fornecer uma URL de compartilhamento do Google Maps.
    
    Args:
        url (str): URL de compartilhamento do Google Maps

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    try:
        latitude, longitude = fetch_coordinates_by_url(url=url)

        if latitude is None or longitude is None:
            return ToolResult(
                content=(
                    "Peça desculpas ao usuário e informe que não foi possível extrair coordenadas geográficas válidas deste link.\n"
                    "Sugira ao usuário que envie o link novamente (verificando se é um link de compartilhamento do Google Maps)"
                )
            )
    except Exception as error:
        return ToolResult(content=str(error))
    
    try:
        properties = fetch_property_by_coordinates_remote(latitude=latitude, longitude=longitude)
    except Exception:
        properties = fetch_property_by_coordinates_locally(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se a URL do Google Maps esta correta."
        )
    
    imgs = retrieve_feature_images([p["spatial_features"]["coordinates"][0] for p in properties])

    run_context.session_state["candidate_properties"] = properties
    
    if len(properties) == 1:
        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = (
            f"  > Identificador CAR: {properties[0]["car_code"]}, "
            f"Tamanho da área: {round(properties[0]["spatial_features"]["total_area"])} ha, "
            f"Município: {properties[0]["spatial_features"]["municipality"]}."
        )

        return ToolResult(
            content=(f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}"),
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        options_text = []
        for i, p in enumerate(properties):
            options_text.append(
                f"  > Opção {i + 1} - Identificador CAR {p["car_code"]}, "
                f"Tamanho da área {round(p["spatial_features"]["total_area"])} ha, "
                f"município de {p["spatial_features"]["municipality"]}."
            )
        result_text = "\n".join(options_text)

        return ToolResult(
            content=(f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}"),
            images=[Image(content=buffer.getvalue())]
            )


@tool(stop_after_tool_call=True)
def select_car_from_list(selection: int, run_context: RunContext):
    """
    Seleciona uma propriedade específica quando a busca retorna múltiplos resultados.
    
    Use esta ferramenta APENAS quando o usuário fornecer um número correspondente a uma das opções apresentadas anteriormente.

    Args:
        selection (int): O número da opção escolhida pelo usuário (ex: 1, 2, 3...).
    """
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)
        
        if not candidate_properties:
            return ToolResult(content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro.")

        if selection < 1 or selection > len(candidate_properties):
            return ToolResult(content=f"Seleção inválida. Escolha um número válido entre 1 e {len(candidate_properties)}.")
        
        selected_property = candidate_properties[selection - 1]

        run_context.session_state['selected_property'] = selected_property
        run_context.session_state['candidate_properties'] = None

        registered_properties = run_context.session_state.get('registered_properties', [])
        run_context.session_state['registered_properties'] = registered_properties + [selected_property]                                 

        return ToolResult(
            content=(
                f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
                "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
            )
        )
    except Exception as e:
        return ToolResult(content=f"[ERRO] Falha ao selecionar: {str(e)}")


@tool(stop_after_tool_call=True)
def confirm_car_selection(run_context: RunContext):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.
    
    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").
    """
    candidate_properties = run_context.session_state.get('candidate_properties', None)
    
    if not candidate_properties:
        return ToolResult(content="Não há propriedade pendente de confirmação. Realize uma busca primeiro.")
    
    selected_property = candidate_properties[0]

    run_context.session_state['selected_property'] = selected_property
    run_context.session_state['candidate_properties'] = None

    registered_properties = run_context.session_state.get('registered_properties', [])
    run_context.session_state['registered_properties'] = registered_properties + [selected_property] 

    return ToolResult(
        content=(
            f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
            "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
        )
    )


@tool(stop_after_tool_call=True)
def reject_car_selection(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    run_context.session_state['candidate_properties'] = None

    return ToolResult(content=("Peça desculpas por não ter encontrado a propriedade correta.\n"))


@tool
def get_selected_property(run_context: RunContext) -> Tuple[str, str]:
    """
    Retorna o nome e o identificador CAR da propriedade selecionada para análises.

    return:
        tuple: Nome e identificador CAR da propriedade selecionada.
    """
    selected_property = run_context.session_state.get('selected_property', None)

    return (selected_property.get("nickname", None), selected_property["car_code"])


@tool
def get_registered_properties(run_context: RunContext) -> List[Tuple[str, str]]:
    """
    Retorna a lista de propriedades registradas no sistema.
    
    return:
        list: Lista de propriedades registradas no sistema.
    """
    registered_properties = run_context.session_state.get('registered_properties', [])

    return [(p.get("nickname", None), p["car_code"]) for p in registered_properties] or None


@tool(stop_after_tool_call=True)
def set_property_name(car: str, name: str, run_context: RunContext):
    """
    Atualizar o nome propriedade registrada no sistema.

    Args:
        car(str): Código de Cadastro Ambiental Rural (CAR)
        name (str): Nome da propriedade.
    """
    selected_property = run_context.session_state.get('selected_property', None)
    
    if selected_property:
        if selected_property["car_code"] == car:
            selected_property["nickname"] = name

    registered_properties = run_context.session_state.get('registered_properties', [])
    for prop in registered_properties:
        if prop.get("car_code") == selected_property.get("car_code"):
            prop["nickname"] = name
            return (
                f"O nome da propriedade {selected_property.get('car_code')} foi definido como '{name}' com sucesso.\n"
                "Seja proativo, use a tool `delegate_task_to_member` e peça ao agente `Agente Extensionista Agrônomo` para fazer um diagnóstico inicial."
            )
        
    return "Nenhuma propriedade selecionada no momento."


def remove_property(car: str, run_context: RunContext) -> str:
    """
    Remove a propriedade selecionada do sistema.

    Args:
        car(str): Código de Cadastro Ambiental Rural (CAR)
    """
    registered_properties = run_context.session_state.get('registered_properties', [])

    flag=False
    new_registered_properties = []
    for prop in registered_properties:
        if prop.get("car_code") == car:
            flag=True
            continue
        
        new_registered_properties.append(prop)

    if not flag:
        return "A propriedade não foi encontrada no sistema."

    selected_car = run_context.session_state.get('selected_property', None)
    if selected_car is not None:
        if selected_car.get("car_code") == car:
            run_context.session_state['selected_property'] = new_registered_properties[-1] if new_registered_properties else None

    run_context.session_state['registered_properties'] = new_registered_properties

    return "A propriedade foi removida com sucesso."


def remove_registered_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    run_context.session_state['registered_properties'] = []
    run_context.session_state['selected_property'] = None

    return "Todas as propriedades foram removidas com sucesso."