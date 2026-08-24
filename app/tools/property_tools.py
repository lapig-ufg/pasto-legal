
from io import BytesIO
from typing import List

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image
from agno.utils.log import log_debug, log_warning, log_error

from app.services.geospatial.sicar import (
    fetch_property_by_car,
    fetch_property_by_coordinates,
    fetch_coordinates_by_url,
    clean_car_code
    )
from app.services.geospatial.image import create_vertical_mosaic
from app.services.geospatial.gee import retrieve_feature_images
from app.schemas.rural_property import RuralProperty


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
    log_debug(f"start_registration_by_coordinate: lat={latitude}, lon={longitude}")
    try:
        properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para lat={latitude}, lon={longitude}")
            return (
                "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                "Peça que tente novamente e verificar se as coordenadas estão corretas."
            )

        registered_map = {prop["car_code"]: prop for prop in run_context.session_state.get("all_properties", [])}
        for prop in properties:
            car_code = prop.car_code
            if car_code in registered_map:
                record = registered_map[car_code]
                property_record = RuralProperty.model_validate(record)
                log_debug(f"Propriedade já registrada: {car_code}")
                return ToolResult(content=str(property_record))

        imgs = retrieve_feature_images([prop.get_coords()[0] for prop in properties])

        run_context.session_state["candidate_properties"] = [prop.model_dump() for prop in properties]

        run_context.session_state["registration_state"] = "pending"

        if len(properties) == 1:
            img = imgs[0]

            buffer = BytesIO()
            img.save(buffer, format="PNG")

            result_text = f"> {properties[0].describe()}"

            log_debug("start_registration_by_coordinate: 1 propriedade encontrada")
            return ToolResult(
                content=f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}",
                images=[Image(content=buffer.getvalue())]
                )

        else:
            mosaic = create_vertical_mosaic(imgs)

            buffer = BytesIO()
            mosaic.save(buffer, format="PNG")

            options_text = []
            for index, prop in enumerate(properties):
                options_text.append(f"  > Opção {index + 1} - {prop.describe()}")
            result_text = "\n".join(options_text)

            log_debug(f"start_registration_by_coordinate: {len(properties)} propriedades encontradas")
            return ToolResult(
                content=f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}",
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_coordinate: {e}")
        return ToolResult(content=str(e))


def start_registration_by_car(run_context: RunContext, car_codes: List[str]):
    """
    Inicia o registro de uma nova propriedade rural baseando-se no código CAR fornecidos.
    
    Use esta ferramenta quando o usuário fornecer um valor de CAR ainda não registrado no sistema.
    
    Args:
        cars (List[str]): Código de Cadastro Ambiental Rural (CAR) no padrão SICAR.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_registration_by_car: car_codes={car_codes}")
    if len(car_codes) > 3:
        log_warning(f"Tentativa de unificar {len(car_codes)} CARs (limite=3)")
        return ToolResult(content=("Peça desculpas e informe que não é permitido unificar mais que 3 CARs por vezes."))

    try:
        clean_car_codes = [clean_car_code(car_code) for car_code in car_codes]

        if None in clean_car_codes:
            log_warning(f"Código CAR inválido recebido: {car_codes}")
            return  ToolResult(
                content=(
                    "Peça desculpas e informe que o sistema aceita exclusivamente o **CAR Federal** (padrão SICAR).\n"
                    "Explique que o padrão exige: 2 letras do Estado, seguidas por 7 números, e terminando com 32 caracteres."
                )
            )

        properties = fetch_property_by_car(car_codes=car_codes)
        _property = RuralProperty.unify(properties)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para CARs={car_codes}")
            return ToolResult(
                content=(
                    "Peça desculpas ao usuário e informe que nenhuma propriedade foi encontrada nesta coordenada.\n"
                    "Peça que tente novamente e verificar se as coordenadas estão corretas."
                )
            )

        run_context.session_state["candidate_properties"] = [_property.model_dump()]

        imgs = retrieve_feature_images(_property.get_coords())

        mosaic = create_vertical_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        result_text = f"  > {_property.describe()}"

        run_context.session_state["registration_state"] = "pending"

        if len(properties) == 1:
            log_debug(f"start_registration_by_car: 1 propriedade encontrada ({_property.car_code})")
            return ToolResult(
                content=(
                    f"Informe ao usuário que a seguinte propriedade foi encontrada:\n{result_text}\n"
                    "Peça que para o usuário confirmar se a propriedade é a correta."),
                images=[Image(content=buffer.getvalue())]
                )

        else:
            log_debug(f"start_registration_by_car: {len(properties)} propriedades unificadas ({_property.car_code})")
            return ToolResult(
                content=(
                    f"Informe ao usuário que as seguintes propriedades foram encontrada:\n{result_text}\n"
                    "Informe que elas foram agrupadas em um único registro que o sistema ira interpretar como uma propriedade única.\n"
                    "Peça que para o usuário confirmar se as propriedades são as corretas."),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_car: {e}")
        return ToolResult(content=str(e))


def start_registration_by_url(run_context: RunContext, url: str) -> ToolResult:
    """
    Inicia o processo de registro de uma nova propriedade rural baseando-se na URL de compartilhamento do Google Maps.

    Use esta ferramenta quando o usuário fornecer uma URL de compartilhamento do Google Maps.
    
    Args:
        url (str): URL de compartilhamento do Google Maps

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_registration_by_url: url={url}")
    try:
        latitude, longitude = fetch_coordinates_by_url(url=url)

        if latitude is None or longitude is None:
            log_warning(f"Não foi possível extrair coordenadas da URL: {url}")
            return ToolResult(
                content=(
                    "Peça desculpas ao usuário e informe que não foi possível extrair coordenadas geográficas válidas deste link.\n"
                    "Sugira ao usuário que envie o link novamente (verificando se é um link de compartilhamento do Google Maps)"
                )
            )
    except Exception as error:
        log_error(f"start_registration_by_url (url parse): {error}")
        return ToolResult(content=str(error))

    try:
        properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para lat={latitude}, lon={longitude}")
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
                log_debug(f"Propriedade já registrada: {car_code}")
                return ToolResult(content=str(property_record))

        imgs = retrieve_feature_images([prop.get_coords()[0] for prop in properties])

        run_context.session_state["candidate_properties"] = [prop.model_dump() for prop in properties]

        run_context.session_state["registration_state"] = "pending"

        if len(properties) == 1:
            img = imgs[0]

            buffer = BytesIO()
            img.save(buffer, format="PNG")

            result_text = f"> {properties[0].describe()}"

            log_debug("start_registration_by_url: 1 propriedade encontrada")
            return ToolResult(
                content=f"Pergunte ao usuário se a seguinte propriedade é a correta:\n{result_text}",
                images=[Image(content=buffer.getvalue())]
                )

        else:
            mosaic = create_vertical_mosaic(imgs)

            buffer = BytesIO()
            mosaic.save(buffer, format="PNG")

            options_text = []
            for index, prop in enumerate(properties):
                options_text.append(f"  > Opção {index + 1} - {prop.describe()}")
            result_text = "\n".join(options_text)

            log_debug(f"start_registration_by_url: {len(properties)} propriedades encontradas")
            return ToolResult(
                content=f"Pergunte ao usuário qual das seguinte propriedades é a correta:\n{result_text}",
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_url: {e}")
        return ToolResult(content=str(e))


def select_car_from_list(run_context: RunContext, selection: int):
    """
    Seleciona uma propriedade específica quando a busca retorna múltiplos resultados.
    
    Use esta ferramenta APENAS quando o usuário fornecer um número correspondente a uma das opções apresentadas anteriormente.

    Args:
        selection (int): O número da opção escolhida pelo usuário (ex: 1, 2, 3...).
    """
    log_debug(f"select_car_from_list: selection={selection}")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)

        if not candidate_properties:
            log_warning("select_car_from_list chamado sem busca prévia")
            return ToolResult(content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro.")

        if selection < 1 or selection > len(candidate_properties):
            log_warning(f"Seleção fora do intervalo: {selection} (1..{len(candidate_properties)})")
            return ToolResult(content=f"Seleção inválida. Escolha um número válido entre 1 e {len(candidate_properties)}.")

        selected_property = candidate_properties[selection - 1]
        run_context.session_state['candidate_properties'] = [selected_property]

        run_context.session_state["registration_state"] = "final"

        log_debug(f"select_car_from_list: CAR {selected_property['car_code']} selecionado")
        return ToolResult(
            content=(
                f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
                "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
            )
        )
    except Exception as e:
        log_error(f"select_car_from_list: {e}")
        return ToolResult(content=str(e))


def confirm_car_selection(run_context: RunContext):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.
    
    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").
    """
    log_debug("confirm_car_selection")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)

        if not candidate_properties:
            log_warning("confirm_car_selection chamado sem propriedade pendente")
            return ToolResult(content="Não há propriedade pendente de confirmação. Realize uma busca primeiro.")

        run_context.session_state["registration_state"] = "final"

        selected_property = candidate_properties[0]
        run_context.session_state['candidate_properties'] = [selected_property]

        log_debug(f"confirm_car_selection: CAR {selected_property['car_code']} confirmado")
        return ToolResult(
            content=(
                f"A propriedade de identificador CAR {selected_property["car_code"]} foi registrada com sucesso."
                "Seja proativo, pergunte ao usuário se ele gostaria de atribuir um nome para a propriedade.\n"
            )
        )
    except Exception as e:
        log_error(f"confirm_car_selection: {e}")
        return ToolResult(content=str(e))


@tool
def complete_registration(run_context: RunContext, name: str):
    """
    Concluir cadastro com o nome da propriedade.

    Use esta ferramente quando o usuário informar o nome da propriedade.
    """
    log_debug(f"complete_registration: name={name}")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)

        selected_property = candidate_properties[0]
        selected_property["nickname"] = name

        all_properties = run_context.session_state.get("all_properties", [])
        all_properties.append(selected_property)

        run_context.session_state["all_properties"] = all_properties
        run_context.session_state["registration_state"] = None
        run_context.session_state['candidate_properties'] = None

        log_debug(f"complete_registration: registro concluído ({selected_property['car_code']})")
        return ToolResult(
            content=(
                "Propriedade registrada com sucesso."
                f"\nNome: {name}"
                f"\nCAR: {selected_property["car_code"]}\n\n"
                "INSTRUÇÃO AO AGENTE: O cadastro foi concluído. Agora você deve entregar "
                "ao usuário o primeiro diagnóstico da propriedade. Para isso:"
                "\n1. Chame imediatamente a ferramenta `get_pasture_stats` passando o "
                f"CAR `{selected_property['car_code']}`."
                "\n2. Com os dados retornados, escreva UM único parágrafo contínuo (2 a 3 "
                "frases fluidas, sem bullet points, títulos ou quebras de linha) confirmando "
                "o cadastro e entregando um insight valioso cruzando as métricas "
                "(oportunidade / alerta de degradação / subutilização)."
                "\n3. Cite no máximo 1 ou 2 dados reais (ex: área total em hectares ou idade "
                "do pasto) para dar embasamento sem jargões."
                "\n4. Use no máximo 1 ou 2 emojis discretos no final."
                "\n5. Finalize com UMA única pergunta-CTA instigante focada num problema "
                "financeiro ou de manejo (ex: calcular Unidade Animal / capacidade de suporte)."
            )
        )
    except Exception as e:
        log_error(f"complete_registration: {e}")
        return ToolResult(content=str(e))


def cancel_registration(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    log_debug("cancel_registration")
    try:
        run_context.session_state["registration_state"] = None
        run_context.session_state['candidate_properties'] = None

        log_debug("cancel_registration: seleção cancelada")
        return ToolResult(content=("Peça desculpas por não ter encontrado a propriedade correta.\n"))
    except Exception as e:
        log_error(f"cancel_registration: {e}")
        return ToolResult(content=str(e))


def set_property_name(run_context: RunContext, car_codes: List[str], name: str):
    """
    Atualizar o nome propriedade registrada no sistema.

    Args:
        car_codes(str): Códigos CAR da propriedade.
        name (str): Nome da propriedade.
    """
    log_debug(f"set_property_name: car_codes={car_codes}, name={name}")
    try:
        all_properties: List[dict] = run_context.session_state.get('all_properties', [])
        selected_property = next((prop for prop in all_properties if prop["car_code"] == ', '.join(car_codes)), None)

        if selected_property is None:
            log_warning(f"Propriedade não encontrada para renomear: {car_codes}")
            return ToolResult(content="Não foi possível registrar o nome da propriedade.")

        updated_selected_property = selected_property
        updated_selected_property["nickname"] = name

        all_properties.remove(selected_property)
        all_properties.append(updated_selected_property)
        run_context.session_state["all_properties"] = all_properties

        log_debug(f"set_property_name: nome atualizado ({', '.join(car_codes)})")
        return ToolResult(
            content=(
                "O nome da propriedade foi alterado com sucesso.\n"
                "Informe ao usuário que ele já pode pedir, em uma nova mensagem, análises da propriedade."
            )
        )
    except Exception as e:
        log_error(f"set_property_name: {e}")
        return ToolResult(content=str(e))


def remove_property(car: str, run_context: RunContext) -> str:
    """
    Remove a propriedade selecionada do sistema.

    Args:
        car(str): Código de Cadastro Ambiental Rural (CAR)
    """
    log_debug(f"remove_property: car={car}")
    try:
        all_properties = run_context.session_state.get('all_properties', [])

        flag=False
        new_all_properties = []
        for prop in all_properties:
            if prop.get("car_code") == car:
                flag=True
                continue

            new_all_properties.append(prop)

        if not flag:
            log_warning(f"Propriedade não encontrada para remoção: {car}")
            return "A propriedade não foi encontrada no sistema."

        selected_car = run_context.session_state.get('selected_property', None)
        if selected_car is not None:
            if selected_car.get("car_code") == car:
                run_context.session_state['selected_property'] = new_all_properties[-1] if new_all_properties else None

        run_context.session_state['all_properties'] = new_all_properties

        log_debug(f"remove_property: CAR {car} removido")
        return "A propriedade foi removida com sucesso."
    except Exception as e:
        log_error(f"remove_property: {e}")
        return str(e)


def remove_all_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    log_debug("remove_all_properties")
    try:
        run_context.session_state['all_properties'] = []
        run_context.session_state['selected_property'] = None

        log_debug("remove_all_properties: todas as propriedades removidas")
        return "Todas as propriedades foram removidas com sucesso."
    except Exception as e:
        log_error(f"remove_all_properties: {e}")
        return str(e)