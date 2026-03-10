import json
import duckdb
import requests

from pathlib import Path
from shapely.geometry import mapping

from app.utils.interfaces.sicar_data_interfaces import PropertyRecord, AreaProperties, SICARProperties

# =====================================================================
# Configuração do Banco de Dados (Engine DuckDB)
# =====================================================================
conn = duckdb.connect(database=':memory:')

conn.execute("INSTALL spatial; LOAD spatial;")
conn.execute("PRAGMA memory_limit='1GB'")
conn.execute("PRAGMA threads=1")


def _map_json_to_property_record(dict: json) -> PropertyRecord:
    pass


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
    geom_geojson = mapping(row['geometry'])
    coordenadas = geom_geojson.get('coordinates', [])

    return PropertyRecord(
        codigo=row.get('cod_imovel', ''),
        area_properties=AreaProperties(
            total_area=row.get('num_area', 0.0),
            municipality=row.get('municipio', ''),
            coordinates=coordenadas
        ),
        sicar_properties=SICARProperties(
            tipo=row.get('ind_tipo', ''),
            status=row.get('ind_status', ''),
            availability_date=row.get('dat_atuali', ''),
            creation_date=row.get('dat_criaca', '')
        )
    )


def fetch_property_by_car_remote(car: str) -> PropertyRecord:
    pass


def fetch_property_by_car_locally(car: str) -> PropertyRecord:
    """
    Busca as informações de um imóvel rural utilizando o código único do CAR.

    Lê diretamente de arquivos Parquet particionados utilizando o DuckDB.

    Args:
        car (str): O código string de registro do imóvel no CAR.

    Returns:
        list[PropertyRecord]: Lista contendo o registro do imóvel encontrado, 
                              ou lista vazia se não encontrar ou ocorrer erro.
    """
    cursor = conn.cursor()
    
    try:
        dataset_path = str(Path.cwd() / 'data' / 'car-br-dataset' / '**' / '*.parquet')

        query = """
            SELECT *
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


def featch_property_by_coordinates_remote(latitude: float, longitude: float) -> list[PropertyRecord]:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://consultapublica.car.gov.br/publico/imoveis/index'
    }

    sess = requests.Session()

    base_url = "https://consultapublica.car.gov.br/publico/imoveis/index"

    sess.get(base_url, verify=False, headers=headers, timeout=10)

    url_api = f'https://consultapublica.car.gov.br/publico/imoveis/getImovel?lat={latitude}&lng={longitude}'
    response = sess.get(url_api, verify=False, headers=headers, timeout=10)

    response.raise_for_status()

    try:
        result = response.json()
    except json.JSONDecodeError:
        raise ValueError("O servidor retornou uma resposta inválida (não é JSON).")

    properties = result

    return properties


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