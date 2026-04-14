import re

from io import BytesIO
from typing import List, Tuple

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image

from app.utils.scripts.sicar_scripts import (
    fetch_property_by_coordinates_locally,
    fetch_property_by_car_locally,
    fetch_coordinates_by_url,
    clean_car_code
    )
from app.utils.scripts.image_scripts import get_mosaic
from app.utils.scripts.gee_scripts import retrieve_feature_images
from app.utils.interfaces.property_record import PropertyRecord, RuralProperty


# TODO: Se o usuário informar uma URL de coordenadas de uma propriedade que já existe no sistema, validar se a propriedade existe por meio do CAR. Se existir então retornar menssagem que já existe.

@tool(stop_after_tool_call=True)
def register_feature_by_coordinate(run_context: RunContext, latitude: float, longitude: float, name: str = None):
    """
    Registra uma nova propriedade rural baseando-se nas coordenadas fornecidas.

    Use esta ferramenta quando o usuário fornecer coordenadas geográficas (latitude/longitude).
    
    Args:
        latitude (float): Latitude em graus decimais.
        longitude (float): Longitude em graus decimais.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    properties = fetch_property_by_coordinates_locally(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se as coordenadas estão corretas."
        )
    
    registered_map = {
        prop["car_code"]: property_record
        for property_record in run_context.session_state.get("registered_properties", [])
        for prop in property_record["properties"]
    }
    for prop in properties:
        car_code = prop["car_code"]
        if car_code in registered_map:
            record = registered_map[car_code]
            property_record = PropertyRecord.model_validate(record) 
            return ToolResult(content=str(property_record))

    run_context.session_state["candidate_properties"] = properties 

    imgs = retrieve_feature_images([prop["spatial_features"]["coordinates"][0] for prop in properties])
    
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
    if len(car_codes > 5):
        return ToolResult(content=("Peça desculpas e informe que não é permitido unificar mais que 3 CARs por vezes."))

    clean_car_codes = [clean_car_code(car_code) for car_code in car_codes]

    if None in clean_car_codes:
        return  ToolResult(
            content=(
                "Peça desculpas e informe que o sistema aceita exclusivamente o **CAR Federal** (padrão SICAR).\n"
                "Explique que o padrão exige: 2 letras do Estado, seguidas por 7 números, e terminando com 32 caracteres."
            )
        )
        
    properties = [fetch_property_by_car_locally(car=car_code) for car_code in clean_car_codes]

    if not properties:
        return ToolResult(
            content=(
                "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                "Peça que tente novamente e verificar se as coordenadas estão corretas."
            )
        )
    
    new_record = PropertyRecord(nickname=name, properties=properties)
    old_registered_properties = run_context.session_state.get("registered_properties", [])
    old_registered_properties.append(new_record.model_dump())
    run_context.session_state["registered_properties"] = old_registered_properties

    imgs = retrieve_feature_images([prop["spatial_features"]["coordinates"][0] for prop in properties])
    
    if len(properties) == 1:
        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = (
            f"  > Identificador CAR: {properties[0]["car_code"]}, "
            f"Tamanho da área: {round(properties[0]["spatial_features"]["total_area"])} ha, "
            f"Município: {properties[0]["spatial_features"]["municipality"]}."
        )

        # TODO: Melhorar prompt de resultado. Uma explicação melhor do estado do sistema.
        return ToolResult(
            content=(
                "Informe ao usuário que a seguinte propriedade foi registrada no sistema:\n"
                f"{result_text}\n"
                "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade."),
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        mosaic = get_mosaic(imgs)

        # TODO: função para fazer mosaico sem números.
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

        # TODO: Melhorar prompt de resultado. Uma explicação melhor do estado do sistema.
        return ToolResult(
            content=(
                "Informe ao usuário que as seguintes propriedades foram unificadas e registradas no sistema:\n"
                f"{result_text}\n"
                "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade."
                ),
            images=[Image(content=buffer.getvalue())]
            )


@tool(stop_after_tool_call=True,)
def register_feature_by_url(run_context: RunContext, url: str) -> ToolResult:
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
    
    properties = fetch_property_by_coordinates_locally(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se a URL do Google Maps esta correta."
        )
    
    registered_map = {
        prop["car_code"]: property_record
        for property_record in run_context.session_state.get("registered_properties", [])
        for prop in property_record["properties"]
    }
    for prop in properties:
        car_code = prop["car_code"]
        if car_code in registered_map:
            record = registered_map[car_code]
            property_record = PropertyRecord.model_validate(record) 
            return ToolResult(content=str(property_record))
    
    run_context.session_state["candidate_properties"] = properties
    
    imgs = retrieve_feature_images([p["spatial_features"]["coordinates"][0] for p in properties])
    
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
                f"  > {i + 1} - Identificador CAR {p["car_code"]}, "
                f"Tamanho da área {round(p["spatial_features"]["total_area"])} ha, "
                f"município de {p["spatial_features"]["municipality"]}."
            )
        result_text = "\n".join(options_text)

        return ToolResult(
            content=(f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}"),
            images=[Image(content=buffer.getvalue())]
            )


@tool(stop_after_tool_call=True)
def select_car_from_list(run_context: RunContext, selection: int):
    """
    Seleciona uma propriedade específica quando a busca retorna múltiplos resultados.
    
    Use esta ferramenta APENAS quando o usuário fornecer um número correspondente a uma das opções apresentadas anteriormente.

    Args:
        selection (int): O número da opção escolhida pelo usuário (ex: 1, 2, 3...).
    """
    candidate_properties = run_context.session_state.get('candidate_properties', None)
    
    if not candidate_properties:
        return ToolResult(content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro.")

    if selection < 1 or selection > len(candidate_properties):
        return ToolResult(content=f"Seleção inválida. Escolha um número válido entre 1 e {len(candidate_properties)}.")
    
    selected_property = candidate_properties[selection - 1]

    run_context.session_state['selected_property'] = selected_property
    run_context.session_state['candidate_properties'] = []

    new_record = PropertyRecord(properties=[RuralProperty.model_validate(selected_property)])
    old_registered_properties = run_context.session_state.get("registered_properties", [])
    old_registered_properties.append(new_record.model_dump())  
    run_context.session_state["registered_properties"] = old_registered_properties                             

    return ToolResult(
        content=(
            f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
            "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
        )
    )


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
    run_context.session_state['candidate_properties'] = []

    new_record = PropertyRecord(properties=[RuralProperty.model_validate(selected_property)])
    old_registered_properties = run_context.session_state.get("registered_properties", [])
    old_registered_properties.append(new_record.model_dump())  
    run_context.session_state["registered_properties"] = old_registered_properties    

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


@tool(stop_after_tool_call=True)
def get_selected_property(run_context: RunContext) -> Tuple[str, str]:
    """
    Retorna o nome e o identificador CAR da propriedade selecionada para análises.

    return:
        tuple: Nome e identificador CAR da propriedade selecionada.
    """
    selected_property = run_context.session_state.get('selected_property', None)

    return (selected_property.get("nickname", None), selected_property["car_code"])


@tool(stop_after_tool_call=True)
def get_registered_properties(run_context: RunContext) -> List[Tuple[str, str]]:
    """
    Retorna a lista de propriedades registradas no sistema.
    
    return:
        list: Lista de propriedades registradas no sistema.
    """
    registered_properties = run_context.session_state.get('registered_properties', [])

    return [(p.get("nickname", None), p["car_code"]) for p in registered_properties] or None


@tool(stop_after_tool_call=True)
def set_property_name(run_context: RunContext, property_id: str, name: str):
    """
    Atualizar o nome propriedade registrada no sistema.

    Args:
        car(str): Código de Cadastro Ambiental Rural (CAR)
        name (str): Nome da propriedade.
    """
    registered_properties = run_context.session_state.get('registered_properties', [])
    selected_property = next((prop for prop in registered_properties if prop["id"] == property_id), None)
    
    if selected_property is None:
        return ToolResult(content="Não foi possível registrar o nome da propriedade.")
    
    new_selected_property = PropertyRecord.model_validate(selected_property)
    new_selected_property.nickname = name

    registered_properties.remove(selected_property)
    registered_properties.append(new_selected_property.model_dump())
    run_context.session_state["registered_properties"] = registered_properties

    return ToolResult(
        content=(
            f"O nome da propriedade foi alterado com sucesso.\n"
            "Seja proativo, use a tool `delegate_task_to_member` e peça ao agente `Agente Extensionista Agrônomo` para fazer um diagnóstico inicial."
        )
    )


@tool(stop_after_tool_call=True)
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


@tool(stop_after_tool_call=True)
def remove_registered_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    run_context.session_state['registered_properties'] = []
    run_context.session_state['selected_property'] = None

    return "Todas as propriedades foram removidas com sucesso."