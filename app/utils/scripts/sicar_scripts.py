import json
import duckdb
import requests

from pathlib import Path
from typing import List
from shapely.geometry import mapping

from app.utils.interfaces.sicar_data_interfaces import PropertyRecord, AreaProperties, SICARProperties
from app.utils.dummy_logger import log

# =====================================================================
# Configuração do Banco de Dados (Engine DuckDB)
# =====================================================================
conn = duckdb.connect(database=':memory:')

conn.execute("INSTALL spatial; LOAD spatial;")
conn.execute("PRAGMA memory_limit='1GB'")
conn.execute("PRAGMA threads=1")


def _map_feature_to_property_record(feature: json) -> PropertyRecord:
    """
    Mapeia uma feature GeoJSON para a estrutura aninhada PropertyRecord.
    
    Recebe um dicionário aninhado (JSON) representando uma entidade geográfica 
    (geralmente oriunda de uma API) e extrai suas propriedades e coordenadas 
    para compor a entidade padronizada.

    Args:
        feature (dict): Dicionário contendo os dados do imóvel no formato GeoJSON, 
                        incluindo as chaves 'properties' e 'geometry'.

    Returns:
        PropertyRecord: Entidade tipada contendo os dados do imóvel divididos 
                        entre AreaProperties e SICARProperties.
    """
    properties = feature.get('properties', {})

    return PropertyRecord(
        codigo=properties.get('codigo', ''),
        area_properties=AreaProperties(
            total_area=properties.get('area', 0.0),
            municipality=properties.get('municipio', ''),
            coordinates=feature.get('geometry', {}).get('coordinates', None)
        ),
        sicar_properties=SICARProperties(
            tipo=properties.get('tipo', ''),
            status=properties.get('status', ''),
            availability_date=properties.get('dataDisponibilizacao', ''),
            creation_date=properties.get('dataCriacao', '')
        )
    )


def _map_row_to_property_record(row: dict) -> PropertyRecord:
    """
    Mapeia uma linha do banco de dados para a estrutura aninhada PropertyRecord.
    
    Recebe um dicionário achatado representando a linha retornada pelo DuckDB e 
    converte a geometria extraída em uma lista de coordenadas padrão GeoJSON.

    Args:
        row (dict): Dicionário contendo os dados do imóvel, incluindo a chave 'geometry'.

    Returns:
        PropertyRecord: Entidade tipada contendo os dados do imóvel divididos 
                        entre AreaProperties e SICARProperties.
    """
    geom_geojson = json.loads(row['geometry'])

    return PropertyRecord(
        codigo=row.get('cod_imovel', ''),
        area_properties=AreaProperties(
            total_area=row.get('num_area', 0.0),
            municipality=row.get('municipio', ''),
            coordinates=[geom_geojson.get('coordinates', [])]
        ),
        sicar_properties=SICARProperties(
            tipo=row.get('ind_tipo', ''),
            status=row.get('ind_status', ''),
            availability_date=row.get('dat_atuali', ''),
            creation_date=row.get('dat_criaca', '')
        )
    )


def fetch_property_by_car_remote(car: str) -> PropertyRecord:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://consultapublica.car.gov.br/publico/imoveis/index'
    }

    base_url = "https://consultapublica.car.gov.br/publico/imoveis/index"
    url_api = f"https://consultapublica.car.gov.br/publico/imoveis/search?text={car}"

    try:
        with requests.Session() as sess:
            sess.get(base_url, verify=False, headers=headers, timeout=10)

            # 2. Faz a chamada real à API
            response = sess.get(url_api, verify=False, headers=headers, timeout=10)
            response.raise_for_status()

            # 3. Parse e validação do JSON
            geo_json = response.json()
            
            features = geo_json.get('features', [])

            return _map_feature_to_property_record(features).model_dump(mode='json')

    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"O servidor do CAR retornou um erro HTTP. Detalhes: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha de conexão ou timeout ao acessar a base pública do CAR. O sistema pode estar instável. Detalhes: {str(e)}")
    except json.JSONDecodeError:
        raise RuntimeError("O servidor do CAR retornou uma resposta inválida (não é um JSON). O site pode estar em manutenção.")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao buscar a propriedade remotamente: {str(e)}")


def fetch_property_by_car_locally(car: str) -> PropertyRecord:
    """
    Busca as informações de um imóvel rural utilizando o código único do CAR.

    Lê diretamente de arquivos Parquet particionados utilizando o DuckDB.

    Args:
        car (str): O código string de registro do imóvel no CAR.

    Returns:
        list[PropertyRecord]: Lista contendo o registro do imóvel encontrado, ou lista vazia se não encontrar ou ocorrer erro.
    """
    cursor = conn.cursor()
    
    try:
        dataset_path = str(Path.cwd() / 'data' / 'car-br-dataset' / '**' / '*.parquet')

        query = """
            SELECT *
                EXCLUDE(geometry),
                ST_AsGeoJSON(geometry) AS geometry
            FROM read_parquet(?)
            WHERE cod_imovel = ?
        """
        
        df = cursor.execute(query, [dataset_path, car]).fetchdf()
        
        if df.empty:
            return None
        
        records_dicts = df.to_dict('records')
        result = [_map_row_to_property_record(row) for row in records_dicts][0]
        
    except Exception as e:
        result = None
    finally:
        cursor.close()
        return result


def fetch_property_by_coordinates_remote(latitude: float, longitude: float) -> List[PropertyRecord]:
    """
    Busca os dados de uma propriedade rural na base pública remota do CAR usando coordenadas.
    
    Args:
        latitude (float): Latitude do ponto de busca (ex: -15.82994).
        longitude (float): Longitude do ponto de busca (ex: -49.43353).

    Returns:
        List[PropertyRecord]: Lista de propriedades mapeadas para a entidade PropertyRecord. Retorna uma lista vazia caso não exista imóvel na coordenada.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://consultapublica.car.gov.br/publico/imoveis/index'
    }

    base_url = "https://consultapublica.car.gov.br/publico/imoveis/index"
    url_api = f"https://consultapublica.car.gov.br/publico/imoveis/getImovel?lat={latitude}&lng={longitude}"

    try:
        with requests.Session() as sess:
            # 1. Acessa a página inicial para capturar cookies de sessão necessários
            sess.get(base_url, verify=False, headers=headers, timeout=10)

            # 2. Faz a chamada real à API
            response = sess.get(url_api, verify=False, headers=headers, timeout=10)
            response.raise_for_status()

            # 3. Parse e validação do JSON
            geo_json = response.json()
            
            features = geo_json.get('features', [])
            
            return [_map_feature_to_property_record(feature) for feature in features]
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"O servidor do CAR retornou um erro HTTP. Detalhes: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha de conexão ou timeout ao acessar a base pública do CAR. O sistema pode estar instável. Detalhes: {str(e)}")
    except json.JSONDecodeError:
        raise RuntimeError("O servidor do CAR retornou uma resposta inválida (não é um JSON). O site pode estar em manutenção.")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao buscar a propriedade remotamente: {str(e)}")


def fetch_property_by_coordinates_locally(latitude: float, longitude: float) -> list[PropertyRecord]:
    """
    Realiza busca geoespacial de imóveis rurais a partir de um ponto (Lat/Lon).

    Utiliza Predicate Pushdown (checagem de min/max bounds) antes de 
    aplicar funções geométricas pesadas para otimizar a leitura do Parquet.

    Args:
        latitude (float): Latitude do ponto de busca (Eixo Y).
        longitude (float): Longitude do ponto de busca (Eixo X).

    Returns:
        list[PropertyRecord]: Lista de imóveis que interceptam a coordenada fornecida.
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
            
    except Exception as e:
        print(f"❌ Erro ao buscar pela coordenada: {e}")
        result = []
    finally:
        cursor.close()
        return result