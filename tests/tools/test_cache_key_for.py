"""
Teste de `_cache_key_for` (`app/tools/analysis_tools.py`) — regressão do bug em
que os caches de `classify_pasture_on_the_fly`/`estimate_pasture_*`
(`pasture_cache.py`) eram chaveados por `selected_property.id` (o NOME
escolhido pelo usuário, mutável e não único: duas propriedades diferentes
chamadas "Fazenda Jaraguá" colidiam no mesmo arquivo de cache, e uma mostrava
silenciosamente o mapa/histórico da outra). O código CAR real (metadado
imutável, único por propriedade) deve ser preferido sempre que disponível.

`app/tools/analysis_tools.py` importa `gee.py`, que inicializa o Earth Engine
na importação do módulo — mesma ressalva de tests/tools/test_confirm_car_selection.py.

    .venv/bin/python -m pytest tests/tools/test_cache_key_for.py -v
"""
from app.schemas.feature import Feature, FeatureMetadata
from app.tools.analysis_tools import _cache_key_for


def _rural_property(feature_id: str, car_code: str) -> Feature:
    return Feature(
        feature_id=feature_id,
        coords=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        metadata=[FeatureMetadata(key="car_code", value=car_code)],
        total_area=23.4674,
        feature_type="rural_property",
    )


def test_cache_key_prefers_car_code_over_friendly_name():
    prop = _rural_property("Fazenda Jaraguá", "GO-5211800-987B29E7E47A4454BAEF582557AB89F3")

    assert _cache_key_for(prop) == "GO-5211800-987B29E7E47A4454BAEF582557AB89F3"


def test_cache_key_stays_unique_for_two_properties_sharing_the_same_friendly_name():
    """A causa raiz do bug: sem o car_code, essas duas colidiriam no mesmo arquivo de cache."""
    farm_a = _rural_property("Fazenda Jaraguá", "GO-5211800-987B29E7E47A4454BAEF582557AB89F3")
    farm_b = _rural_property("Fazenda Jaraguá", "SP-3550308-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    assert _cache_key_for(farm_a) != _cache_key_for(farm_b)


def test_cache_key_falls_back_to_feature_id_without_car_code():
    buffer_area = Feature(
        feature_id="Buffer_1",
        coords=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        metadata=[],
        total_area=1.0,
        feature_type="buffer_area",
    )

    assert _cache_key_for(buffer_area) == "Buffer_1"
