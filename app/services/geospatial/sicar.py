import re
import json
import ssl
import duckdb
import requests
import urllib3

from pathlib import Path
from typing import List, Dict
from requests.adapters import HTTPAdapter

from agno.utils.log import log_debug, log_error

from app.schemas.property_feature import RuralProperty, SpatialFeatures, SicarMetadata
from app.configs.config import config

# Suppress InsecureRequestWarning since we use verify=False for SICAR requests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =====================================================================
# SICAR Session Handling
# =====================================================================

class DedupCookieJar(requests.cookies.RequestsCookieJar):
    """CookieJar that deduplicates cookies with the same name/domain/path.

    SICAR sends duplicate PLAY_SESSION cookies which causes the default
    CookieJar to crash with "There are multiple cookies with name, 'PLAY_SESSION'".
    """

    def set_cookie(self, cookie, *args, **kwargs):
        existing = self._cookies.get(cookie.domain, {}).get(cookie.path, {}).get(cookie.name)
        if existing is not None:
            self.clear(cookie.domain, cookie.path, cookie.name)
        super().set_cookie(cookie, *args, **kwargs)


class TLSAdapter(HTTPAdapter):
    """HTTPAdapter with SECLEVEL=0 to fix SSL handshake failure in Docker.

    The python:3.12-slim image uses OpenSSL SECLEVEL=1 by default, which
    rejects the SICAR server's certificate/cipher suite.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


_SICAR_BASE_URL = "https://consultapublica.car.gov.br/publico/imoveis/index"
_SICAR_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://consultapublica.car.gov.br/publico/imoveis/index',
}


def _sicar_session_request(url_api: str, timeout: int = 100) -> requests.Response:
    """Execute a SICAR API request with the Play Framework session flow.

    1. Visit the base page to establish initial cookies
    2. Call the API — returns a 302 redirect that sets PLAY_SESSION
    3. Follow the redirect to activate the session
    4. Call the API again with the valid session to get JSON data
    """
    sess = requests.Session()
    sess.cookies = DedupCookieJar()
    sess.mount('https://', TLSAdapter())

    # Visit base page to establish session
    sess.get(_SICAR_BASE_URL, verify=False, headers=_SICAR_HEADERS, timeout=timeout)

    # Call the API — expect a 302 redirect with PLAY_SESSION cookie
    api_resp = sess.get(url_api, verify=False, headers=_SICAR_HEADERS, timeout=timeout, allow_redirects=False)

    if api_resp.status_code == 302:
        # Follow the redirect to activate the session, then call the API again
        redirect_url = api_resp.headers.get('Location', '')
        if redirect_url.startswith('http://'):
            redirect_url = redirect_url.replace('http://', 'https://', 1)

        sess.get(redirect_url, verify=False, headers=_SICAR_HEADERS, timeout=timeout)
        response = sess.get(url_api, verify=False, headers=_SICAR_HEADERS, timeout=timeout)
    else:
        response = api_resp

    response.raise_for_status()
    return response


# =====================================================================
# Configuração do Banco de Dados (Engine DuckDB)
# =====================================================================
conn = duckdb.connect(database=':memory:')

conn.execute("LOAD spatial;")
conn.execute("PRAGMA memory_limit='1GB'")
conn.execute("PRAGMA threads=1")


def _map_feature_to_property_record(feature: json) -> RuralProperty:
    """
    Mapeia uma feature GeoJSON para a estrutura aninhada RuralProperty.

    Recebe um dicionário aninhado (JSON) representando uma entidade geográfica
    (geralmente oriunda de uma API) e extrai suas propriedades e coordenadas
    para compor a entidade padronizada.

    Args:
        feature (dict): Dicionário contendo os dados do imóvel no formato GeoJSON, incluindo as chaves 'properties' e 'geometry'.

    Returns:
        RuralProperty: Entidade tipada contendo os dados do imóvel divididos entre AreaProperties e SICARProperties.
    """
    properties = feature.get('properties', {})

    return RuralProperty(
        car_code=properties.get('codigo', ''),
        spatial_features=SpatialFeatures(
            total_area=properties.get('area', 0.0),
            municipality=properties.get('municipio', ''),
            coordinates=feature.get('geometry', {}).get('coordinates', None)
        ),
        sicar_metadata=SicarMetadata(
            tipo=properties.get('tipo', ''),
            status=properties.get('status', ''),
            availability_date=properties.get('dataDisponibilizacao', ''),
            creation_date=properties.get('dataCriacao', '')
        )
    )


def _map_row_to_property_record(row: dict) -> RuralProperty:
    """
    Mapeia uma linha do banco de dados para a estrutura aninhada RuralProperty.

    Recebe um dicionário achatado representando a linha retornada pelo DuckDB e
    converte a geometria extraída em uma lista de coordenadas padrão GeoJSON.

    Args:
        row (dict): Dicionário contendo os dados do imóvel, incluindo a chave 'geometry'.

    Returns:
        Dict: Entidade tipada contendo os dados do imóvel divididos entre AreaProperties e SICARProperties.
    """
    geom_geojson = json.loads(row['geometry'])

    return RuralProperty(
        car_code=row.get('cod_imovel', ''),
        spatial_features=SpatialFeatures(
            total_area=row.get('num_area', 0.0),
            municipality=row.get('municipio', ''),
            coordinates=[geom_geojson.get('coordinates', [])]
        ),
        sicar_metadata=SicarMetadata(
            tipo=row.get('ind_tipo', ''),
            status=row.get('ind_status', ''),
            availability_date=row.get('dat_atuali', ''),
            creation_date=row.get('dat_criaca', '')
        )
    )


def __fetch_property_by_car_remote(car_codes: List[str]) -> List[RuralProperty] | None:
    """
    Busca os dados de propriedades rurais na base pública remota do CAR usando códigos CAR.

    Args:
        car_codes (List[str]): Lista de códigos CAR para busca.

    Returns:
        List[RuralProperty] | None: Lista de propriedades mapeadas, ou None se não encontrar.
    """
    all_features = []

    for car in car_codes:
        url_api = f"https://consultapublica.car.gov.br/publico/imoveis/search?text={car}"

        try:
            response = _sicar_session_request(url_api)
            geo_json = response.json()

        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"O servidor do CAR retornou um erro HTTP. Detalhes: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Falha de conexão ou timeout ao acessar a base pública do CAR. O sistema pode estar instável. Detalhes: {str(e)}")
        except json.JSONDecodeError:
            raise RuntimeError("O servidor do CAR retornou uma resposta inválida (não é um JSON). O site pode estar em manutenção.")
        except Exception as e:
            raise RuntimeError(f"Erro inesperado ao buscar a propriedade remotamente: {str(e)}")

        features = geo_json.get('features', [])
        if features:
            all_features.extend(features)

    if not all_features:
        return None

    return [_map_feature_to_property_record(feature) for feature in all_features]


def __fetch_property_by_car_locally(car_codes: List[str]) -> List[RuralProperty]:
    """
    Busca as informações de imóveis rurais utilizando uma lista de códigos únicos do CAR.

    Lê diretamente de arquivos Parquet particionados utilizando o DuckDB.

    Args:
        car_codes (List[str]): Lista de códigos string de registro dos imóveis no CAR.

    Returns:
        List[Dict] | None: Lista contendo os registros dos imóveis encontrados, ou None se não encontrar ou ocorrer erro.
    """
    # Retorna precocemente se a lista estiver vazia para evitar erro de sintaxe no SQL
    if not car_codes:
        return None

    cursor = conn.cursor()

    try:
        dataset_path = str(Path.cwd() / 'data' / 'car-br-dataset' / '**' / '*.parquet')

        # Cria a string de placeholders ex: "?, ?, ?" dependendo do tamanho da lista
        placeholders = ', '.join(['?'] * len(car_codes))

        query = f"""
            SELECT *
                EXCLUDE(geometry),
                ST_AsGeoJSON(geometry) AS geometry
            FROM read_parquet(?)
            WHERE cod_imovel IN ({placeholders})
        """

        # Junta o path do dataset com os códigos da lista para passar como parâmetros
        params = [dataset_path] + car_codes

        df = cursor.execute(query, params).fetchdf()

        if df.empty:
            return []

        records_dicts = df.to_dict('records')
        result = [_map_row_to_property_record(row) for row in records_dicts]

    except Exception as e:
        # É recomendável pelo menos logar o erro caso 'result = None' oculte o problema
        log_error(f"Erro ao buscar imóveis: {e}")
        result = []
    finally:
        cursor.close()

    return result


def __fetch_property_by_coordinates_remote(latitude: float, longitude: float) -> List[RuralProperty]:
    """
    Busca os dados de uma propriedade rural na base pública remota do CAR usando coordenadas.

    Args:
        latitude (float): Latitude do ponto de busca (ex: -15.82994).
        longitude (float): Longitude do ponto de busca (ex: -49.43353).

    Returns:
        List[RuralProperty]: Lista de propriedades mapeadas para a entidade RuralProperty.
            Retorna None caso não exista imóvel na coordenada.
    """
    url_api = f"https://consultapublica.car.gov.br/publico/imoveis/getImovel?lat={latitude}&lng={longitude}"

    try:
        response = _sicar_session_request(url_api)
        geo_json = response.json()

    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"O servidor do CAR retornou um erro HTTP. Detalhes: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha de conexão ou timeout ao acessar a base pública do CAR. O sistema pode estar instável. Detalhes: {str(e)}")
    except json.JSONDecodeError:
        raise RuntimeError("O servidor do CAR retornou uma resposta inválida (não é um JSON). O site pode estar em manutenção.")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao buscar a propriedade remotamente: {str(e)}")

    features = geo_json.get('features', [])

    if not features:
        return None

    return [_map_feature_to_property_record(feature) for feature in features]


def __fetch_property_by_coordinates_locally(latitude: float, longitude: float) -> List[RuralProperty]:
    """
    Realiza busca geoespacial de imóveis rurais a partir de um ponto (Lat/Lon).

    Utiliza Predicate Pushdown (checagem de min/max bounds) antes de
    aplicar funções geométricas pesadas para otimizar a leitura do Parquet.

    Args:
        latitude (float): Latitude do ponto de busca (Eixo Y).
        longitude (float): Longitude do ponto de busca (Eixo X).

    Returns:
        list[Dict]: Lista de imóveis que interceptam a coordenada fornecida.
    """
    cursor = conn.cursor()

    try:
        dataset_path = str(Path.cwd() / 'data' / 'car-br-dataset' / '**' / '*.parquet')

        query = """
            SELECT *
                EXCLUDE(geometry),
                ST_AsGeoJSON(geometry) AS geometry
            FROM read_parquet(?)
            WHERE
                ? BETWEEN min_x AND max_x
                AND ? BETWEEN min_y AND max_y
                AND ST_Intersects(geometry, ST_Point(?, ?))
        """

        df = cursor.execute(query, [
            dataset_path,
            longitude, latitude,
            longitude, latitude
        ]).fetchdf()

        if df.empty:
            return []

        records_dicts = df.to_dict('records')
        result = [_map_row_to_property_record(row) for row in records_dicts]

    except Exception:
        result = []
    finally:
        cursor.close()

    return result


def fetch_coordinates_by_url(url: str) -> tuple[float | None, float | None]:
    """
    Acessa uma URL, segue os redirecionamentos e extrai as coordenadas geográficas
    (latitude e longitude) da URL final.

    Args:
        url (str): A URL de origem a ser acessada e inspecionada.

    Returns:
        tuple[float | None, float | None]: Uma tupla contendo (latitude, longitude)
        como números de ponto flutuante. Retorna (None, None) se as coordenadas não
        forem encontradas na URL final ou se ocorrer um erro na requisição.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
        response.raise_for_status()

        url_final = response.url

        match_url = re.search(r'/maps/(?:place|search)(?:.*)/\@?(-?\d+\.\d+),\+?(-?\d+\.\d+)', url_final)
        if match_url:
            return float(match_url.group(1)), float(match_url.group(2))

        raise RuntimeError(f"Nenhuma coordenada foi encontrada para essa URL.")

    except requests.RequestException as e:
        raise RuntimeError((
            f"Erro ao acessar a URL: {e}"
            "Peça desculpa e peça que o usuário tente novamente mais tarde."
        ))


def clean_car_code(car_code: str) -> str | None:
    """
    Valida e normaliza o formato de um código CAR (Cadastro Ambiental Rural).

    Extrai o código via Regex, removendo pontos separadores e padronizando
    os hifens obrigatórios entre a UF, o número sequencial e o identificador.
    """
    pattern = r"\b([A-Z]{2})-?(\d{7})-([A-Z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\b"

    search = re.search(pattern, car_code, flags=re.IGNORECASE)
    if not search:
        return None

    return re.sub(pattern, r"\1-\2-\3\4\5\6\7\8\9\10", search[0], flags=re.IGNORECASE)


if config.APP_ENV == "development":
    fetch_property_by_car = __fetch_property_by_car_remote
    fetch_property_by_coordinates = __fetch_property_by_coordinates_remote
else:
    fetch_property_by_car = __fetch_property_by_car_locally
    fetch_property_by_coordinates = __fetch_property_by_coordinates_locally