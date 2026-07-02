import re

from io import BytesIO
from typing import List

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image
from agno.utils.log import log_debug

from app.utils.scripts.sicar_scripts import (
    fetch_property_by_car,
    fetch_property_by_coordinates,
    fetch_coordinates_by_url,
    clean_car_code
    )
from app.utils.scripts.image_scripts import get_mosaic
from app.utils.scripts.gee_scripts import retrieve_feature_images
from app.utils.interfaces.property_record import RuralProperty
from app.utils.interfaces.workflow_state import WorkflowState, WorkflowRouteEnum


def _clear_session_state(run_context: RunContext):
    run_context.session_state["workflow_route"] = None
    run_context.session_state["registration_state"] = None

    run_context.session_state['candidate_properties'] = None


def start_registration_by_coordinate(run_context: RunContext, latitude: float, longitude: float):
    """
    Iniciar o registro de uma nova propriedade rural baseando-se nas coordenadas fornecidas.

    Use esta ferramenta quando o usuário fornecer coordenadas geográficas (latitude/longitude).
    
    Args:
        latitude (float): Latitude em graus decimais.
        longitude (float): Longitude em graus decimais.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se as coordenadas estão corretas."
        )
    
    run_context.session_state["workflow_route"] = "property_manager_agent"
    
    registered_map = {prop["car_code"]: prop for prop in run_context.session_state.get("all_properties", [])}
    for prop in properties:
        car_code = prop.car_code
        if car_code in registered_map:
            record = registered_map[car_code]
            property_record = RuralProperty.model_validate(record) 
            return ToolResult(content=str(property_record)) 

    imgs = retrieve_feature_images([prop.get_coords()[0] for prop in properties])

    run_context.session_state["candidate_properties"] = [prop.model_dump() for prop in properties]

    run_context.session_state["registration_state"] = "pending"
    run_context.session_state["workflow_route"] = "property_manager_agent"
    
    if len(properties) == 1:
        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = f"> {properties[0].describe()}"

        return ToolResult(
            content=f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}",
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        options_text = []
        for index, prop in enumerate(properties):
            options_text.append(f"  > Opção {index + 1} - {prop.describe()}")
        result_text = "\n".join(options_text)

        return ToolResult(
            content=f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}",
            images=[Image(content=buffer.getvalue())]
            )


def start_registration_by_car(run_context: RunContext, car_codes: List[str]):
    """
    Inicia o registro de uma nova propriedade rural baseando-se no código CAR fornecidos.
    
    Use esta ferramenta quando o usuário fornecer um valor de CAR ainda não registrado no sistema.
    
    Args:
        cars (List[str]): Código de Cadastro Ambiental Rural (CAR) no padrão SICAR.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    if len(car_codes) > 3:
        return ToolResult(content=("Peça desculpas e informe que não é permitido unificar mais que 3 CARs por vezes."))

    clean_car_codes = [clean_car_code(car_code) for car_code in car_codes]

    if None in clean_car_codes:
        return  ToolResult(
            content=(
                "Peça desculpas e informe que o sistema aceita exclusivamente o **CAR Federal** (padrão SICAR).\n"
                "Explique que o padrão exige: 2 letras do Estado, seguidas por 7 números, e terminando com 32 caracteres."
            )
        )
        
    properties = fetch_property_by_car(car_codes=car_codes)
    _property = RuralProperty.unify(properties)

    if not properties:
        return ToolResult(
            content=(
                "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                "Peça que tente novamente e verificar se as coordenadas estão corretas."
            )
        )
    
    run_context.session_state["workflow_route"] = "property_manager_agent"

    run_context.session_state["candidate_properties"] = [_property.model_dump()] 

    imgs = retrieve_feature_images(_property.get_coords())

    mosaic = get_mosaic(imgs)

    buffer = BytesIO()
    mosaic.save(buffer, format="PNG")

    result_text = f"  > {_property.describe()}"

    run_context.session_state["registration_state"] = "pending"
    run_context.session_state["workflow_route"] = "property_manager_agent"
    
    if len(properties) == 1:
        return ToolResult(
            content=(
                f"Informe ao usuário que a seguinte propriedade foi encontrada:\n{result_text}\n"
                "Peça que para o usuário confirmar se a propriedade é a correta."),
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        return ToolResult(
            content=(
                f"Informe ao usuário que as seguintes propriedades foram encontrada:\n{result_text}\n"
                "Informe que elas foram agrupadas em um único registro que o sistema ira interpretar como uma propriedade única.\n"
                "Peça que para o usuário confirmar se as propriedades são as corretas."),
            images=[Image(content=buffer.getvalue())]
            )


def start_registration_by_url(run_context: RunContext, url: str) -> ToolResult:
    """
    Inicia o processo de registro de uma nova propriedade rural baseando-se na URL de compartilhamento do Google Maps.

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
    
    properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

    if not properties:
        return (
            "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
            "Peça que tente novamente e verificar se as coordenadas estão corretas."
        )
    
    registered_map = {
        prop["car_code"]: prop
        for prop in run_context.session_state.get("all_properties", [])
    }
    for prop in properties:
        car_code = prop.car_code
        if car_code in registered_map:
            record = registered_map[car_code]
            property_record = RuralProperty.model_validate(record) 
            return ToolResult(content=str(property_record))

    imgs = retrieve_feature_images([prop.get_coords()[0] for prop in properties])

    run_context.session_state["candidate_properties"] = [prop.model_dump() for prop in properties] 

    run_context.session_state["registration_state"] = "pending"
    run_context.session_state["workflow_route"] = "property_manager_agent"
    
    if len(properties) == 1:
        img = imgs[0]

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        result_text = f"> {properties[0].describe()}"

        return ToolResult(
            content=f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}",
            images=[Image(content=buffer.getvalue())]
            )
    
    else:
        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        options_text = []
        for index, prop in enumerate(properties):
            options_text.append(f"  > Opção {index + 1} - {prop.describe()}")
        result_text = "\n".join(options_text)

        return ToolResult(
            content=f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}",
            images=[Image(content=buffer.getvalue())]
            )


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
    run_context.session_state['candidate_properties'] = [selected_property]

    run_context.session_state["registration_state"] = "final"                        

    return ToolResult(
        content=(
            f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
            "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
        )
    )


def confirm_car_selection(run_context: RunContext):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.
    
    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").
    """
    candidate_properties = run_context.session_state.get('candidate_properties', None)
    
    if not candidate_properties:
        return ToolResult(content="Não há propriedade pendente de confirmação. Realize uma busca primeiro.")
    
    run_context.session_state["registration_state"] = "final"
    
    selected_property = candidate_properties[0]
    run_context.session_state['candidate_properties'] = [selected_property]       

    return ToolResult(
        content=(
            f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
            "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
        )
    )


def cancel_registration(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    _clear_session_state(run_context)

    return ToolResult(content=("Peça desculpas por não ter encontrado a propriedade correta.\n"))


def set_property_name(run_context: RunContext, car_codes: List[str], name: str):
    """
    Atualizar o nome propriedade registrada no sistema.

    Args:
        car_codes(str): Códigos CAR da propriedade.
        name (str): Nome da propriedade.
    """
    candidate_properties = run_context.session_state.get('candidate_properties', None)

    if not candidate_properties is None:
        selected_property = candidate_properties[0]
        selected_property["nickname"] = name

        old_all_properties = run_context.session_state.get("all_properties", [])
        old_all_properties.append(selected_property)  

        run_context.session_state["all_properties"] = old_all_properties

        _clear_session_state(run_context)

        workflow_state = WorkflowState.model_validate(run_context.session_state["workflow_state"])        
        workflow_state.route = WorkflowRouteEnum.ANALYST
        workflow_state.active_router_loop = True
        run_context.session_state["workflow_state"] = workflow_state.model_dump()

        return ToolResult(
            content=f"Faça um diagnóstico inicial para a propriedade de código CAR: {selected_property["car_code"]}."
        )

    all_properties: List[dict] = run_context.session_state.get('all_properties', [])
    selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)
    
    if selected_property is None:
        return ToolResult(content="Não foi possível registrar o nome da propriedade.")
    
    run_context.session_state["workflow_route"] = None
    
    updated_selected_property = selected_property
    updated_selected_property["nickname"] = name

    all_properties.remove(selected_property)
    all_properties.append(updated_selected_property)
    run_context.session_state["all_properties"] = all_properties

    _clear_session_state(run_context)

    return ToolResult(
        content=(
            f"O nome da propriedade foi alterado com sucesso.\n"
            "Seja proativo, use a tool `delegate_task_to_member` e peça ao agente `Agente Extensionista Agrônomo` para fazer um diagnóstico inicial."
        )
    )


def remove_property(car: str, run_context: RunContext) -> str:
    """
    Remove a propriedade selecionada do sistema.

    Args:
        car(str): Código de Cadastro Ambiental Rural (CAR)
    """
    all_properties = run_context.session_state.get('all_properties', [])

    flag=False
    new_all_properties = []
    for prop in all_properties:
        if prop.get("car_code") == car:
            flag=True
            continue
        
        new_all_properties.append(prop)

    if not flag:
        return "A propriedade não foi encontrada no sistema."

    selected_car = run_context.session_state.get('selected_property', None)
    if selected_car is not None:
        if selected_car.get("car_code") == car:
            run_context.session_state['selected_property'] = new_all_properties[-1] if new_all_properties else None

    run_context.session_state['all_properties'] = new_all_properties

    return "A propriedade foi removida com sucesso."


def remove_all_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    run_context.session_state['all_properties'] = []
    run_context.session_state['selected_property'] = None

    return "Todas as propriedades foram removidas com sucesso."