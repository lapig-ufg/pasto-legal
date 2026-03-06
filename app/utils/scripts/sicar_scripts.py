import geopandas as gpd

from pathlib import Path
from shapely.geometry import Point, mapping

from app.utils.interfaces.sicar_data_interfaces import PropertyRecord, AreaProperties, SICARProperties


def _map_row_to_property_record(row: dict) -> PropertyRecord:
    """
    Mapeia uma linha do banco de dados (dict plano) para a estrutura aninhada do PropertyRecord.
    Também converte a geometria do Shapely para a lista de coordenadas do GeoJSON.
    """
    # Extrai as coordenadas da geometria do Shapely usando a função mapping
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


def fetch_property_by_car(car: str) -> dict:
    """
    Busca as informações de um imóvel rural utilizando o código do CAR.

    Esta função realiza a leitura otimizada de um dataset em formato Parquet,
    aplicando um filtro de metadados direto na leitura (predicate pushdown).
    Isso impede que o arquivo inteiro seja carregado na memória, mantendo 
    o consumo de RAM estritamente baixo.

    Args:
        car (str): O código do Cadastro Ambiental Rural (CAR) a ser buscado.

    Returns:
        dict: Um dicionário contendo os atributos do imóvel encontrado 
        (sem a geometria). Retorna um dicionário vazio caso o imóvel não 
        seja encontrado ou ocorra algum erro.
    """
    try:
        dataset_path = Path.cwd() / 'data' / 'car-br-dataset'
        
        car_filter = [('cod_imovel', '==', car)]
        
        gdf = gpd.read_parquet(dataset_path, filters=car_filter)
        
        if gdf.empty:
            return {}
        
        records_dicts = gdf.to_dict('records')
        return [_map_row_to_property_record(row) for row in records_dicts]
        
    except Exception as e:
        print(f"❌ Erro ao buscar pelo código CAR: {e}")
        return {}


def fetch_property_by_coordinates(latitude: float, longitude: float):
    """
    Busca as informações de um imóvel rural a partir de uma coordenada geográfica.

    A função utiliza o bounding box (bbox) do ponto para carregar apenas os
    polígonos daquela região específica do dataset Parquet, otimizando o uso de RAM.
    Em seguida, realiza a interseção espacial fina para garantir que o ponto
    está contido no polígono do imóvel.

    Args:
        latitude (float): Latitude do ponto de busca.
        longitude (float): Longitude do ponto de busca.

    Returns:
        dict: Um dicionário contendo os atributos do imóvel que intersecta 
        a coordenada (sem a geometria). Retorna um dicionário vazio se não 
        houver interseção ou em caso de erro.
    """
    point = Point(longitude, latitude)
    point_bbox = (longitude, latitude, longitude, latitude)

    try:
        dataset_path = Path.cwd() / 'data' / 'car-br-dataset'

        gdf = gpd.read_parquet(dataset_path, bbox=point_bbox)
        
        if gdf.empty:
            return {}
            
        intersections = gdf[gdf.intersects(point)]
        
        if not intersections.empty:
            records_dicts = intersections.to_dict('records')
            return [_map_row_to_property_record(row) for row in records_dicts]
        else:
            return {}
            
    except Exception as e:
        print(f"❌ Erro ao ler o dataset: {e}")