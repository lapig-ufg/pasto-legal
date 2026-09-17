
from io import BytesIO
from typing import List

from semente.context import Context as RunContext
from semente import tool
from semente import ToolResult
from semente import Image
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description
from semente.configs.prompts import get_tool_result_text

from domain.services.geospatial.sicar import (
    fetch_property_by_car,
    fetch_property_by_coordinates,
    fetch_coordinates_by_url,
    clean_car_code
    )
from domain.services.geospatial.image import create_vertical_mosaic
from domain.services.geospatial.gee import retrieve_feature_images
from domain.services.geospatial.geometry import build_buffered_area
from domain.schemas.feature import Feature, FeatureMetadata, RegisteredFeatures
from domain.utils.feature_utils import get_registered_features, set_registered_features

# Bounds of the buffer radius accepted by the buffer registration tools (meters).
_MIN_RADIUS_METERS = 50
_MAX_RADIUS_METERS = 1000
_DEFAULT_RADIUS_METERS = 200

# Instruction appended when a SICAR lookup finds nothing and the buffer
# fallback registers an area instead (see _register_buffer_candidate).
# Rendered from tools.yml (property_tools.*.results.sicar_miss_buffer_fallback).
_SICAR_MISS_BUFFER_TOOL_KEY = "sicar_miss_buffer_fallback"


def _register_buffer_candidate(
    run_context: RunContext,
    latitude: float,
    longitude: float,
    radius: int = _DEFAULT_RADIUS_METERS,
) -> tuple[Feature, bytes]:
    """
    Builds a buffer area candidate from a coordinate and radius, stores it in
    the session as the pending registration and renders its image.

    Shared by the buffer registration tools and by the SICAR tools fallback
    (when no property exists in the SICAR database). Does not validate the
    radius bounds; callers must do it beforehand.

    Returns:
        Tuple (Feature, PNG image bytes) on success. Raises on failure; the
        caller's ``except`` renders the tool-specific error text.
    """
    try:
        buffer_area = build_buffered_area(latitude=latitude, longitude=longitude, radius=radius)

        imgs = retrieve_feature_images(buffer_area.get_coords())

        run_context.session_state["candidate_properties"] = [buffer_area.model_dump()]

        run_context.session_state["registration_state"] = "pending"

        img = imgs[0]

        buffer_stream = BytesIO()
        img.save(buffer_stream, format="PNG")

        return buffer_area, buffer_stream.getvalue()
    except Exception as e:
        log_error(f"_register_buffer_candidate: {e}")
        raise


def _validate_buffer_radius(radius: int, tool_key: str) -> ToolResult | None:
    """
    Returns a ToolResult with the out-of-range instructions (rendered from
    tools.yml ``results.invalid_radius``) when the radius is outside
    [_MIN_RADIUS_METERS, _MAX_RADIUS_METERS], or None when valid.
    """
    if not (_MIN_RADIUS_METERS <= radius <= _MAX_RADIUS_METERS):
        log_warning(f"Raio fora do intervalo permitido: {radius}")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", tool_key, "invalid_radius",
                min_radius=_MIN_RADIUS_METERS, max_radius=_MAX_RADIUS_METERS,
            )
        )
    return None


@tool(description=get_tool_description("property_tools", "start_registration_by_coordinate"))
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
            fallback = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude)

            _, img_bytes = fallback
            return ToolResult(
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_coordinate", _SICAR_MISS_BUFFER_TOOL_KEY
                ),
                images=[Image(content=img_bytes)]
            )

        registered_features = get_registered_features(run_context.session_state)
        for prop in properties:
            duplicate = registered_features.find_by_any(prop.id)
            if duplicate is not None:
                log_debug(f"Propriedade já registrada: {prop.id}")
                return ToolResult(content=str(duplicate))

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
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_coordinate",
                    "confirm_single_property", property_details=result_text,
                ),
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
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_coordinate",
                    "confirm_multiple_options", options=result_text,
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_coordinate: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_registration_by_coordinate", "error", error=e))


@tool(description=get_tool_description("property_tools", "start_registration_by_car"))
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
        return ToolResult(content=get_tool_result_text("property_tools", "start_registration_by_car", "too_many_cars"))

    try:
        clean_car_codes = [clean_car_code(car_code) for car_code in car_codes]

        if None in clean_car_codes:
            log_warning(f"Código CAR inválido recebido: {car_codes}")
            return ToolResult(
                content=get_tool_result_text("property_tools", "start_registration_by_car", "invalid_car_format"),
            )

        properties = fetch_property_by_car(car_codes=car_codes)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para CARs={car_codes}")
            return ToolResult(
                content=get_tool_result_text("property_tools", "start_registration_by_car", "sicar_not_found_instructions"),
            )

        _property = Feature.unify(properties)

        run_context.session_state["candidate_properties"] = [_property.model_dump()]

        imgs = retrieve_feature_images(_property.get_coords())

        mosaic = create_vertical_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")

        result_text = f"  > {_property.describe()}"

        run_context.session_state["registration_state"] = "pending"

        if len(properties) == 1:
            log_debug(f"start_registration_by_car: 1 propriedade encontrada ({_property.get_metadata('car_code')})")
            return ToolResult(
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_car",
                    "confirm_single_car", property_details=result_text,
                ),
                images=[Image(content=buffer.getvalue())]
                )

        else:
            log_debug(f"start_registration_by_car: {len(properties)} propriedades unificadas ({_property.get_metadata('car_code')})")
            return ToolResult(
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_car",
                    "confirm_unified_cars", property_details=result_text,
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_car: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_registration_by_car", "error", error=e))


@tool(description=get_tool_description("property_tools", "start_buffer_registration_by_coordinate"))
def start_buffer_registration_by_coordinate(run_context: RunContext, latitude: float, longitude: float, radius: int = _DEFAULT_RADIUS_METERS):
    """
    Iniciar o registro de uma nova área de buffer baseando-se em um ponto
    (coordenada) e um raio em metros, gerando um buffer circular ao redor do ponto.

    Use esta ferramenta quando o usuário indicar um ponto de interesse no mapa
    e quiser registrar a área ao redor dele, sem possuir um código CAR.
    Nenhuma busca no CAR é realizada; a área é gerada localmente.

    Args:
        latitude (float): Latitude em graus decimais do ponto central.
        longitude (float): Longitude em graus decimais do ponto central.
        radius (int): Raio do buffer em metros (50 a 1000). Padrão: 200.

    Returns:
        ToolResult: Resultado contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_buffer_registration_by_coordinate: lat={latitude}, lon={longitude}, radius={radius}")
    try:
        invalid_radius = _validate_buffer_radius(radius, "start_buffer_registration_by_coordinate")
        if invalid_radius is not None:
            return invalid_radius

        buffer_area, img_bytes = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude, radius=radius)

        result_text = f"> {buffer_area.describe()}"

        log_debug(f"start_buffer_registration_by_coordinate: área gerada ({buffer_area.id}, {radius} m)")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", "start_buffer_registration_by_coordinate",
                "confirm_buffer_area", area_details=result_text,
            ),
            images=[Image(content=img_bytes)]
            )
    except Exception as e:
        log_error(f"start_buffer_registration_by_coordinate: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_buffer_registration_by_coordinate", "error", error=e))


@tool(description=get_tool_description("property_tools", "start_buffer_registration_by_url"))
def start_buffer_registration_by_url(run_context: RunContext, url: str, radius: int = _DEFAULT_RADIUS_METERS) -> ToolResult:
    """
    Inicia o registro de uma nova área de buffer baseando-se na URL de
    compartilhamento do Google Maps e em um raio em metros, gerando um buffer
    circular ao redor do ponto indicado na URL.

    Use esta ferramenta quando o usuário fornecer uma URL de compartilhamento
    do Google Maps e quiser registrar a área ao redor do ponto, sem possuir um
    código CAR. Nenhuma busca no CAR é realizada; a área é gerada localmente.

    Args:
        url (str): URL de compartilhamento do Google Maps.
        radius (int): Raio do buffer em metros (50 a 1000). Padrão: 200.

    Returns:
        ToolResult: Resultado contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_buffer_registration_by_url: url={url}, radius={radius}")
    try:
        invalid_radius = _validate_buffer_radius(radius, "start_buffer_registration_by_url")
        if invalid_radius is not None:
            return invalid_radius

        latitude, longitude = fetch_coordinates_by_url(url=url)

        if latitude is None or longitude is None:
            log_warning(f"Não foi possível extrair coordenadas da URL: {url}")
            return ToolResult(
                content=get_tool_result_text("property_tools", "start_buffer_registration_by_url", "url_coords_not_extracted"),
            )
    except Exception as error:
        log_error(f"start_buffer_registration_by_url (url parse): {error}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_buffer_registration_by_url", "error", error=error))

    try:
        buffer_area, img_bytes = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude, radius=radius)

        result_text = f"> {buffer_area.describe()}"

        log_debug(f"start_buffer_registration_by_url: área gerada ({buffer_area.id}, {radius} m)")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", "start_buffer_registration_by_url",
                "confirm_buffer_area", area_details=result_text,
            ),
            images=[Image(content=img_bytes)]
            )
    except Exception as e:
        log_error(f"start_buffer_registration_by_url: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_buffer_registration_by_url", "error", error=e))


@tool(description=get_tool_description("property_tools", "start_registration_by_url"))
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
                content=get_tool_result_text("property_tools", "start_registration_by_url", "url_coords_not_extracted"),
            )
    except Exception as error:
        log_error(f"start_registration_by_url (url parse): {error}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_registration_by_url", "error", error=error))

    try:
        properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para lat={latitude}, lon={longitude}")
            _, img_bytes = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude)
            return ToolResult(
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_url", _SICAR_MISS_BUFFER_TOOL_KEY
                ),
                images=[Image(content=img_bytes)]
            )

        registered_features = get_registered_features(run_context.session_state)
        for prop in properties:
            duplicate = registered_features.find_by_any(prop.id)
            if duplicate is not None:
                log_debug(f"Propriedade já registrada: {prop.id}")
                return ToolResult(content=str(duplicate))

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
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_url",
                    "confirm_single_property", property_details=result_text,
                ),
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
                content=get_tool_result_text(
                    "property_tools", "start_registration_by_url",
                    "confirm_multiple_options", options=result_text,
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_url: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "start_registration_by_url", "error", error=e))


@tool(description=get_tool_description("property_tools", "select_car_from_list"))
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
            return ToolResult(content=get_tool_result_text("property_tools", "select_car_from_list", "no_search_yet"))

        if selection < 1 or selection > len(candidate_properties):
            log_warning(f"Seleção fora do intervalo: {selection} (1..{len(candidate_properties)})")
            return ToolResult(content=get_tool_result_text(
                "property_tools", "select_car_from_list", "selection_out_of_range",
                max_selection=len(candidate_properties),
            ))

        selected_property = candidate_properties[selection - 1]
        run_context.session_state['candidate_properties'] = [selected_property]

        run_context.session_state["registration_state"] = "final"

        selected_id = Feature.model_validate(selected_property).id
        log_debug(f"select_car_from_list: feição {selected_id} selecionada")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", "select_car_from_list", "success_registered_prompt_name",
                feature_id=selected_id,
            )
        )
    except Exception as e:
        log_error(f"select_car_from_list: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "select_car_from_list", "error", error=e))


@tool(description=get_tool_description("property_tools", "confirm_car_selection"))
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
            return ToolResult(content=get_tool_result_text("property_tools", "confirm_car_selection", "no_pending_property"))

        run_context.session_state["registration_state"] = "final"

        selected_property = candidate_properties[0]
        run_context.session_state['candidate_properties'] = [selected_property]

        selected_id = Feature.model_validate(selected_property).id
        log_debug(f"confirm_car_selection: feição {selected_id} confirmada")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", "confirm_car_selection", "success_registered_prompt_name",
                feature_id=selected_id,
            )
        )
    except Exception as e:
        log_error(f"confirm_car_selection: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "confirm_car_selection", "error", error=e))


@tool(description=get_tool_description("property_tools", "complete_registration"))
def complete_registration(run_context: RunContext, name: str):
    """
    Concluir cadastro com o nome da propriedade.

    Use esta ferramente quando o usuário informar o nome da propriedade.
    """
    log_debug(f"complete_registration: name={name}")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)

        # The user-chosen name is stored as metadata; feature_id stays stable
        # (CAR code for rural properties, generated id for buffers).
        candidate = Feature.model_validate(candidate_properties[0])
        metadata = [entry for entry in candidate.metadata if entry.key != "name"]
        metadata.append(FeatureMetadata(key="name", value=name))
        registered_feature = candidate.model_copy(update={"metadata": metadata})

        registered_features = get_registered_features(run_context.session_state)
        registered_features.features.append(registered_feature)
        set_registered_features(run_context.session_state, registered_features)

        run_context.session_state["registration_state"] = None
        run_context.session_state['candidate_properties'] = None

        registered_id = registered_feature.id
        log_debug(f"complete_registration: registro concluído ({registered_id})")
        return ToolResult(
            content=get_tool_result_text(
                "property_tools", "complete_registration", "success_registration_complete",
                name=name, feature_id=registered_id,
            )
        )
    except Exception as e:
        log_error(f"complete_registration: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "complete_registration", "error", error=e))


@tool(description=get_tool_description("property_tools", "cancel_registration"))
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
        return ToolResult(content=get_tool_result_text("property_tools", "cancel_registration", "cancelled_apology"))
    except Exception as e:
        log_error(f"cancel_registration: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "cancel_registration", "error", error=e))


@tool(description=get_tool_description("property_tools", "set_property_name"))
def set_property_name(run_context: RunContext, feature_id: str, name: str):
    """
    Atualizar o nome propriedade registrada no sistema.

    Args:
        feature_id (str): Identificador (id) da feição registrada.
        name (str): Nome da propriedade.
    """
    log_debug(f"set_property_name: feature_id={feature_id}, name={name}")
    try:
        registered_features = get_registered_features(run_context.session_state)

        target = registered_features.find_by_any(feature_id)
        if target is None:
            log_warning(f"Propriedade não encontrada para renomear: {feature_id}")
            return ToolResult(content=get_tool_result_text("property_tools", "set_property_name", "property_not_found"))

        # The new name is stored as metadata; feature_id is stable.
        index = registered_features.features.index(target)
        metadata = [entry for entry in target.metadata if entry.key != "name"]
        metadata.append(FeatureMetadata(key="name", value=name))
        registered_features.features[index] = target.model_copy(update={"metadata": metadata})
        set_registered_features(run_context.session_state, registered_features)

        log_debug(f"set_property_name: nome atualizado ({feature_id} -> {name})")
        return ToolResult(
            content=get_tool_result_text("property_tools", "set_property_name", "success_renamed")
        )
    except Exception as e:
        log_error(f"set_property_name: {e}")
        return ToolResult(content=get_tool_result_text("property_tools", "set_property_name", "error", error=e))


@tool(description=get_tool_description("property_tools", "remove_property"))
def remove_property(feature_id: str, run_context: RunContext) -> str:
    """
    Remove a propriedade selecionada do sistema.

    Args:
        feature_id (str): Identificador (id) da feição registrada.
    """
    log_debug(f"remove_property: feature_id={feature_id}")
    try:
        registered_features = get_registered_features(run_context.session_state)

        removed_feature = registered_features.find_by_any(feature_id)

        if removed_feature is None:
            log_warning(f"Propriedade não encontrada para remoção: {feature_id}")
            return get_tool_result_text("property_tools", "remove_property", "property_not_found")

        remaining_features = [
            feature
            for feature in registered_features.features
            if feature is not removed_feature
        ]
        registered_features.features = remaining_features
        set_registered_features(run_context.session_state, registered_features)

        selected_car = run_context.session_state.get('selected_property', None)
        if selected_car is not None:
            selected_feature = Feature.model_validate(selected_car)
            if selected_feature.id == removed_feature.id:
                run_context.session_state['selected_property'] = (
                    remaining_features[-1].model_dump() if remaining_features else None
                )

        log_debug(f"remove_property: feição {feature_id} removida")
        return get_tool_result_text("property_tools", "remove_property", "success_removed")
    except Exception as e:
        log_error(f"remove_property: {e}")
        return get_tool_result_text("property_tools", "remove_property", "error", error=e)


@tool(description=get_tool_description("property_tools", "remove_all_properties"))
def remove_all_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    log_debug("remove_all_properties")
    try:
        set_registered_features(run_context.session_state, RegisteredFeatures())
        run_context.session_state['selected_property'] = None

        log_debug("remove_all_properties: todas as propriedades removidas")
        return get_tool_result_text("property_tools", "remove_all_properties", "success_removed_all")
    except Exception as e:
        log_error(f"remove_all_properties: {e}")
        return get_tool_result_text("property_tools", "remove_all_properties", "error", error=e)
