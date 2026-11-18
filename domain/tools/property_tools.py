
from io import BytesIO
from typing import List, Optional

from semente.context import Context as RunContext
from semente import tool
from semente import ToolResult
from semente import File, Image
from semente.logging import log_debug, log_warning, log_error

from domain.services.geospatial.sicar import (
    fetch_property_by_car,
    fetch_property_by_coordinates,
    fetch_coordinates_by_url,
    clean_car_code
    )
from domain.services.geospatial.image import create_vertical_mosaic
from domain.services.geospatial.gee import retrieve_feature_images, retrieve_property_overview_image
from domain.services.geospatial.geometry import build_buffered_area
from domain.services.geospatial.geojson_io import (
    GeoFileError,
    build_features_from_geojson,
)
from domain.schemas.feature import Feature, FeatureMetadata, RegisteredFeatures
from domain.utils.feature_utils import get_registered_features, set_registered_features

# Bounds of the buffer radius accepted by the buffer registration tools (meters).
_MIN_RADIUS_METERS = 50
_MAX_RADIUS_METERS = 1000
_DEFAULT_RADIUS_METERS = 200


def _unexpected_error(error: Exception) -> str:
    return f"Erro inesperado: {error}."


def _first_geojson_bytes(files: Optional[List[File]]) -> Optional[bytes]:
    """
    Returns the content of the first GeoJSON file attached to the conversation
    (``format == "geojson"``), or None when there is none.

    The input step converts every supported geospatial document (shapefile
    .zip/.rar, KMZ, KML, GeoJSON) to GeoJSON and attaches it as a .json file;
    the framework injects those files into the ``files`` parameter.
    """
    for file in files or []:
        if getattr(file, "format", None) == "geojson" and file.content:
            return file.content
    return None


def _register_buffer_candidate(
    run_context: RunContext,
    latitude: float,
    longitude: float,
    radius: int = _DEFAULT_RADIUS_METERS,
) -> tuple[Feature, bytes]:
    """
    Builds a buffer area candidate from a coordinate and radius, stores it in
    the session as the pending registration and renders its image.

    Shared by the buffer registration tools. Does not validate the radius
    bounds; callers must do it beforehand.

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


def _validate_buffer_radius(radius: int) -> ToolResult | None:
    """
    Returns a ToolResult with the out-of-range instructions when the radius is
    outside [_MIN_RADIUS_METERS, _MAX_RADIUS_METERS], or None when valid.
    """
    if not (_MIN_RADIUS_METERS <= radius <= _MAX_RADIUS_METERS):
        log_warning(f"Raio fora do intervalo permitido: {radius}")
        return ToolResult(
            content=(
                "Peça desculpas ao usuário e informe que o raio deve estar entre "
                f"{_MIN_RADIUS_METERS} e {_MAX_RADIUS_METERS} metros."
            )
        )
    return None


@tool()
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
            return ToolResult(
                content=(
                    "Nenhuma propriedade foi encontrada na base do SICAR para esta "
                    f"localização (lat {latitude}, lon {longitude}).\n"
                    "NÃO inicie nenhum registro automaticamente.\n"
                    "Informe ao usuário que não há imóvel registrado no SICAR neste "
                    "ponto e pergunte se ele deseja registrar uma área de buffer ao "
                    "redor dele (raio entre 50 e 1000 metros, padrão 200 metros).\n"
                    "Se o usuário aceitar, chame a ferramenta "
                    f"`start_buffer_registration_by_coordinate` com latitude {latitude} "
                    f"e longitude {longitude} (e o raio escolhido, se o usuário "
                    "informar).\n"
                    "Se o usuário recusar, encerre a operação."
                ),
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
                content=(
                    "Pergunte ao usuário se a seguinte propriedade é a correta:\n"
                    f"{result_text}"
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
                content=(
                    "Pergunte ao usuário qual das seguinte propriedades é a correta:\n"
                    f"{result_text}"
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_coordinate: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def start_registration_by_geojson(
    run_context: RunContext,
    files: Optional[List[File]] = None,
):
    """
    Inicia o registro de uma nova propriedade rural a partir de um arquivo
    geoespacial enviado pelo usuário (shapefile .zip/.rar, KMZ, KML ou GeoJSON),
    que foi convertido para GeoJSON e anexado à conversa como um arquivo .json.

    Use esta ferramenta quando o usuário enviar um arquivo de mapa com os
    limites da propriedade (ou dos piquetes).

    IMPORTANTE: NÃO copie nem passe o conteúdo do arquivo .json. O sistema lê
    o arquivo anexado automaticamente. Apenas chame a ferramenta sem argumentos.

    Returns:
        ToolResult: Resultado contendo imagem e instruções para o próximo passo.
    """
    log_debug("start_registration_by_geojson")

    content = _first_geojson_bytes(files)
    if content is None:
        log_warning("start_registration_by_geojson chamado sem arquivo geoespacial anexado")
        return ToolResult(
            content=(
                "Peça desculpas e informe que não encontrou nenhum arquivo "
                "geoespacial anexado.\nPeça ao usuário que envie o arquivo novamente "
                "(shapefile .zip/.rar, KMZ, KML ou GeoJSON)."
            )
        )

    try:
        property_feature, paddocks = build_features_from_geojson(content)
    except GeoFileError as e:
        log_warning(f"start_registration_by_geojson: geojson inválido - {e}")
        return ToolResult(
            content=(
                "Peça desculpas e informe que não foi possível interpretar o arquivo "
                "geoespacial enviado.\nPeça ao usuário que confira o arquivo e envie "
                "novamente (shapefile .zip/.rar, KMZ, KML ou GeoJSON)."
            )
        )
    except Exception as e:
        log_error(f"start_registration_by_geojson (parse): {e}")
        return ToolResult(content=_unexpected_error(e))

    try:
        paddock_labels = [(paddock.coords, paddock.feature_id) for paddock in paddocks]
        img = retrieve_property_overview_image(property_feature.coords, paddocks=paddock_labels or None)

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        run_context.session_state["candidate_properties"] = [property_feature.model_dump()]
        run_context.session_state["pending_paddocks"] = [paddock.model_dump() for paddock in paddocks]
        run_context.session_state["registration_state"] = "pending"

        result_text = f"> {property_feature.describe()}"
        if paddocks:
            paddocks_text = ", ".join(paddock.feature_id for paddock in paddocks)
            result_text = f"{result_text}\nPiquetes identificados: {paddocks_text}"

        log_debug(f"start_registration_by_geojson: propriedade gerada ({property_feature.id}, {len(paddocks)} piquetes)")
        return ToolResult(
            content=(
                "Pergunte ao usuário se a propriedade delimitada na imagem é a "
                f"correta:\n{result_text}\nSe houver piquetes, explique que cada "
                "piquete foi identificado com um rótulo na imagem."
            ),
            images=[Image(content=buffer.getvalue())],
        )
    except Exception as e:
        log_error(f"start_registration_by_geojson: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def start_registration_by_car(run_context: RunContext, car_codes: List[str]):
    """
    Inicia o registro de uma nova propriedade rural baseando-se no código CAR fornecidos.

    Use esta ferramenta quando o usuário fornecer um valor de CAR ainda não registrado no sistema.

    Args:
        car_codes (List[str]): Código de Cadastro Ambiental Rural (CAR) no padrão SICAR.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_registration_by_car: car_codes={car_codes}")
    if len(car_codes) > 3:
        log_warning(f"Tentativa de unificar {len(car_codes)} CARs (limite=3)")
        return ToolResult(
            content="Peça desculpas e informe que não é permitido unificar mais que 3 CARs por vezes."
        )

    try:
        clean_car_codes = [clean_car_code(car_code) for car_code in car_codes]

        if None in clean_car_codes:
            log_warning(f"Código CAR inválido recebido: {car_codes}")
            return ToolResult(
                content=(
                    "Peça desculpas e informe que o sistema aceita exclusivamente o "
                    "**CAR Federal** (padrão SICAR).\nExplique que o padrão exige: "
                    "2 letras do Estado, seguidas por 7 números, e terminando com 32 "
                    "caracteres."
                ),
            )

        properties = fetch_property_by_car(car_codes=car_codes)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para CARs={car_codes}")
            return ToolResult(
                content=(
                    "Nenhuma propriedade foi encontrada na base do SICAR para o(s) "
                    "CAR(s) informado(s).\nComo não há imóvel registrado no SICAR, o "
                    "registro só pode ser feito como área de buffer.\nExplique isso ao "
                    "usuário e peça que ele envie um link de compartilhamento do Google "
                    "Maps ou as coordenadas (latitude/longitude) do local.\nEm seguida, "
                    "registre a área chamando a ferramenta "
                    "`start_buffer_registration_by_url` (para o link) ou "
                    "`start_buffer_registration_by_coordinate` (para as coordenadas)."
                ),
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
                content=(
                    "Informe ao usuário que a seguinte propriedade foi encontrada:\n"
                    f"{result_text}\nPeça que para o usuário confirmar se a propriedade "
                    "é a correta."
                ),
                images=[Image(content=buffer.getvalue())]
                )

        else:
            log_debug(f"start_registration_by_car: {len(properties)} propriedades unificadas ({_property.get_metadata('car_code')})")
            return ToolResult(
                content=(
                    "Informe ao usuário que as seguintes propriedades foram encontrada:\n"
                    f"{result_text}\nInforme que elas foram agrupadas em um único "
                    "registro que o sistema ira interpretar como uma propriedade única.\n"
                    "Peça que para o usuário confirmar se as propriedades são as corretas."
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_car: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def start_buffer_registration_by_coordinate(run_context: RunContext, latitude: float, longitude: float, radius: int = _DEFAULT_RADIUS_METERS):
    """
    Iniciar o registro de uma nova área de buffer baseando-se em um ponto
    (coordenada) e um raio em metros, gerando um buffer circular ao redor do ponto.

    Use esta ferramenta quando o usuário indicar um ponto de interesse no mapa
    e quiser registrar a área ao redor dele, sem possuir um código CAR e sem
    imóvel registrado na base do SICAR. Nenhuma busca no SICAR é realizada;
    a área é gerada localmente.

    Args:
        latitude (float): Latitude em graus decimais do ponto central.
        longitude (float): Longitude em graus decimais do ponto central.
        radius (int): Raio do buffer em metros (50 a 1000). Padrão: 200.

    Returns:
        ToolResult: Resultado contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_buffer_registration_by_coordinate: lat={latitude}, lon={longitude}, radius={radius}")
    try:
        invalid_radius = _validate_buffer_radius(radius)
        if invalid_radius is not None:
            return invalid_radius

        buffer_area, img_bytes = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude, radius=radius)

        result_text = f"> {buffer_area.describe()}"

        log_debug(f"start_buffer_registration_by_coordinate: área gerada ({buffer_area.id}, {radius} m)")
        return ToolResult(
            content=(
                "Pergunte ao usuário se a seguinte área é a correta:\n"
                f"{result_text}"
            ),
            images=[Image(content=img_bytes)]
            )
    except Exception as e:
        log_error(f"start_buffer_registration_by_coordinate: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def start_buffer_registration_by_url(run_context: RunContext, url: str, radius: int = _DEFAULT_RADIUS_METERS) -> ToolResult:
    """
    Iniciar o registro de uma nova área de buffer baseando-se na URL de
    compartilhamento do Google Maps e em um raio em metros, gerando um buffer
    circular ao redor do ponto indicado na URL.

    Use esta ferramenta quando o usuário fornecer uma URL de compartilhamento
    do Google Maps e quiser registrar a área ao redor do ponto, sem possuir um
    código CAR e sem imóvel registrado na base do SICAR. Nenhuma busca no SICAR
    é realizada; a área é gerada localmente.

    Args:
        url (str): URL de compartilhamento do Google Maps.
        radius (int): Raio do buffer em metros (50 a 1000). Padrão: 200.

    Returns:
        ToolResult: Resultado contendo imagem e instruções para o próximo passo.
    """
    log_debug(f"start_buffer_registration_by_url: url={url}, radius={radius}")
    try:
        invalid_radius = _validate_buffer_radius(radius)
        if invalid_radius is not None:
            return invalid_radius

        latitude, longitude = fetch_coordinates_by_url(url=url)

        if latitude is None or longitude is None:
            log_warning(f"Não foi possível extrair coordenadas da URL: {url}")
            return ToolResult(
                content=(
                    "Peça desculpas ao usuário e informe que não foi possível extrair "
                    "coordenadas geográficas válidas deste link.\nSugira ao usuário que "
                    "envie o link novamente (verificando se é um link de "
                    "compartilhamento do Google Maps)"
                ),
            )
    except Exception as error:
        log_error(f"start_buffer_registration_by_url (url parse): {error}")
        return ToolResult(content=_unexpected_error(error))

    try:
        buffer_area, img_bytes = _register_buffer_candidate(run_context, latitude=latitude, longitude=longitude, radius=radius)

        result_text = f"> {buffer_area.describe()}"

        log_debug(f"start_buffer_registration_by_url: área gerada ({buffer_area.id}, {radius} m)")
        return ToolResult(
            content=(
                "Pergunte ao usuário se a seguinte área é a correta:\n"
                f"{result_text}"
            ),
            images=[Image(content=img_bytes)]
            )
    except Exception as e:
        log_error(f"start_buffer_registration_by_url: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
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
                    "Peça desculpas ao usuário e informe que não foi possível extrair "
                    "coordenadas geográficas válidas deste link.\nSugira ao usuário que "
                    "envie o link novamente (verificando se é um link de "
                    "compartilhamento do Google Maps)"
                ),
            )
    except Exception as error:
        log_error(f"start_registration_by_url (url parse): {error}")
        return ToolResult(content=_unexpected_error(error))

    try:
        properties = fetch_property_by_coordinates(latitude=latitude, longitude=longitude)

        if not properties:
            log_warning(f"Nenhuma propriedade encontrada para lat={latitude}, lon={longitude}")
            return ToolResult(
                content=(
                    "Nenhuma propriedade foi encontrada na base do SICAR para esta "
                    "localização.\nNÃO inicie nenhum registro automaticamente.\n"
                    "Informe ao usuário que não há imóvel registrado no SICAR neste "
                    "ponto e pergunte se ele deseja registrar uma área de buffer ao "
                    "redor dele (raio entre 50 e 1000 metros, padrão 200 metros).\n"
                    "Se o usuário aceitar, chame a ferramenta "
                    f"`start_buffer_registration_by_url` com a URL {url} (e o raio "
                    "escolhido, se o usuário informar).\n"
                    "Se o usuário recusar, encerre a operação."
                ),
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
                content=(
                    "Pergunte ao usuário se a seguinte propriedade é a correta:\n"
                    f"{result_text}"
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
                content=(
                    "Pergunte ao usuário qual das seguinte propriedades é a correta:\n"
                    f"{result_text}"
                ),
                images=[Image(content=buffer.getvalue())]
                )
    except Exception as e:
        log_error(f"start_registration_by_url: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
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
            return ToolResult(
                content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro."
            )

        if selection < 1 or selection > len(candidate_properties):
            log_warning(f"Seleção fora do intervalo: {selection} (1..{len(candidate_properties)})")
            return ToolResult(
                content=(
                    "Seleção inválida. Escolha um número válido entre 1 e "
                    f"{len(candidate_properties)}."
                )
            )

        selected_property = candidate_properties[selection - 1]
        run_context.session_state['candidate_properties'] = [selected_property]

        run_context.session_state["registration_state"] = "final"

        selected_id = Feature.model_validate(selected_property).id
        log_debug(f"select_car_from_list: feição {selected_id} selecionada")
        return ToolResult(
            content=(
                f"A propriedade de identificador {selected_id} foi registrada com "
                "sucesso. Seja proativo, pergunte ao usuário se ele gostaria de "
                "atribuir um nome para a propriedade."
            )
        )
    except Exception as e:
        log_error(f"select_car_from_list: {e}")
        return ToolResult(content=_unexpected_error(e))


def _persist_registration(run_context: RunContext, candidate_properties: list, name: str) -> ToolResult:
    """
    Lógica compartilhada de conclusão de cadastro (persiste a feição com o nome
    escolhido em metadata, registra piquetes pendentes, zera o estado de
    registro). Usada tanto por `complete_registration` (fluxo normal, nome
    pedido num turno separado) quanto por `confirm_car_selection` quando o
    usuário já dá o nome junto com a confirmação — sem isso,
    `registration_state` ficava travado em "final" pra sempre nesse segundo
    caso, porque `complete_registration` só fica disponível pro agente DEPOIS
    que esse estado já foi setado (ou seja, nunca no mesmo turno da confirmação).

    O id permanece estável (CAR/buffer); o nome vive em metadata['name'].
    """
    candidate = Feature.model_validate(candidate_properties[0])
    metadata = [entry for entry in candidate.metadata if entry.key != "name"]
    metadata.append(FeatureMetadata(key="name", value=name))
    registered_feature = candidate.model_copy(update={"metadata": metadata})

    registered_features = get_registered_features(run_context.session_state)
    registered_features.features.append(registered_feature)

    # Paddocks (from a geospatial file registration) are registered with
    # the paddock number kept on the stable id and the display name
    # "{name}_{n}" stored as metadata.
    pending_paddocks = run_context.session_state.get("pending_paddocks") or []
    for paddock in pending_paddocks:
        paddock_feature = Feature.model_validate(paddock)
        paddock_number = str(paddock_feature.feature_id).rsplit("_", 1)[-1]
        paddock_metadata = [
            entry for entry in paddock_feature.metadata if entry.key != "name"
        ]
        paddock_metadata.append(FeatureMetadata(key="name", value=f"{name}_{paddock_number}"))
        registered_features.features.append(
            paddock_feature.model_copy(update={"metadata": paddock_metadata})
        )

    set_registered_features(run_context.session_state, registered_features)

    run_context.session_state["registration_state"] = None
    run_context.session_state['candidate_properties'] = None
    run_context.session_state["pending_paddocks"] = None

    registered_id = registered_feature.id
    log_debug(f"_persist_registration: registro concluído ({registered_id}, {len(pending_paddocks)} piquetes)")
    return ToolResult(
        content=(
            "Propriedade registrada com sucesso.\n"
            f"Nome: {name}\n"
            f"Feature ID: {registered_id}\n\n"
            "INSTRUÇÃO AO AGENTE: O cadastro foi concluído. Agora você deve entregar "
            "ao usuário o primeiro diagnóstico da propriedade."
        )
    )


@tool()
def confirm_car_selection(run_context: RunContext, name: Optional[str] = None):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.

    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").

    Se o usuário já disser o nome desejado NA MESMA mensagem da confirmação
    (ex: "Sim, confirmo. Pode chamar de Fazenda Boa Vista"), passe esse nome
    no parâmetro `name` — o cadastro é concluído imediatamente, sem esperar
    outro turno. Sem isso, o usuário fica sem acesso às ferramentas de
    análise (boletim, mapas etc.) até responder de novo com o nome.
    """
    log_debug(f"confirm_car_selection: name={name}")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)

        if not candidate_properties:
            log_warning("confirm_car_selection chamado sem propriedade pendente")
            return ToolResult(
                content=(
                    "Não há propriedade pendente de confirmação. Realize uma busca "
                    "primeiro."
                )
            )

        if name:
            return _persist_registration(run_context, candidate_properties, name)

        run_context.session_state["registration_state"] = "final"

        selected_property = candidate_properties[0]
        run_context.session_state['candidate_properties'] = [selected_property]

        selected_id = Feature.model_validate(selected_property).id
        log_debug(f"confirm_car_selection: feição {selected_id} confirmada")
        return ToolResult(
            content=(
                f"A propriedade de identificador {selected_id} foi registrada com "
                "sucesso. Seja proativo, pergunte ao usuário se ele gostaria de "
                "atribuir um nome para a propriedade."
            )
        )
    except Exception as e:
        log_error(f"confirm_car_selection: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def complete_registration(run_context: RunContext, name: str):
    """
    Concluir cadastro com o nome da propriedade.

    Use esta ferramente quando o usuário informar o nome da propriedade.
    """
    log_debug(f"complete_registration: name={name}")
    try:
        candidate_properties = run_context.session_state.get('candidate_properties', None)
        return _persist_registration(run_context, candidate_properties, name)
    except Exception as e:
        log_error(f"complete_registration: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
def cancel_registration(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    log_debug("cancel_registration")
    try:
        run_context.session_state["registration_state"] = None
        run_context.session_state['candidate_properties'] = None
        run_context.session_state["pending_paddocks"] = None

        log_debug("cancel_registration: seleção cancelada")
        return ToolResult(
            content="Peça desculpas por não ter encontrado a propriedade correta."
        )
    except Exception as e:
        log_error(f"cancel_registration: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
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
            return ToolResult(
                content="Não foi possível registrar o nome da propriedade."
            )

        # The new name is stored as metadata; feature_id is stable.
        index = registered_features.features.index(target)
        metadata = [entry for entry in target.metadata if entry.key != "name"]
        metadata.append(FeatureMetadata(key="name", value=name))
        registered_features.features[index] = target.model_copy(update={"metadata": metadata})
        set_registered_features(run_context.session_state, registered_features)

        log_debug(f"set_property_name: nome atualizado ({feature_id} -> {name})")
        return ToolResult(
            content=(
                "O nome da propriedade foi alterado com sucesso.\nInforme ao usuário "
                "que ele já pode pedir, em uma nova mensagem, análises da propriedade."
            )
        )
    except Exception as e:
        log_error(f"set_property_name: {e}")
        return ToolResult(content=_unexpected_error(e))


@tool()
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
            return "A propriedade não foi encontrada no sistema."

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
        return "A propriedade foi removida com sucesso."
    except Exception as e:
        log_error(f"remove_property: {e}")
        return _unexpected_error(e)


@tool()
def remove_all_properties(run_context: RunContext) -> str:
    """
    Remove todas as propriedades registradas no sistema.
    """
    log_debug("remove_all_properties")
    try:
        set_registered_features(run_context.session_state, RegisteredFeatures())
        run_context.session_state['selected_property'] = None

        log_debug("remove_all_properties: todas as propriedades removidas")
        return "Todas as propriedades foram removidas com sucesso."
    except Exception as e:
        log_error(f"remove_all_properties: {e}")
        return _unexpected_error(e)
