"""
Teste de integração real (GEE + Xee) para a classificação de pastagem on-the-fly.

Diferente de test_persona_calibration.py, este teste NÃO injeta credenciais falsas:
`app/utils/scripts/gee_scripts.py` inicializa o Earth Engine na importação do módulo,
então este teste precisa de um `.env` real na raiz do projeto (GEE_PROJECT,
GEE_SERVICE_ACCOUNT, GEE_KEY_FILE, APP_ENV) para rodar.

    .venv/bin/python -m pytest tests/ee_scripts/test_pasture_classification.py -v
"""
import json
import shutil
from pathlib import Path

import ee
import pytest

from app.services.geospatial.pasture_classification import (
    _cache_paths,
    _latest_mapbiomas_year,
    classify_pasture_on_the_fly,
)

_ROOT = Path(__file__).resolve().parents[2]
_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"


def _load_test_properties():
    features = json.loads(_MOCK_PATH.read_text())["features"]
    properties = []
    for feature in features:
        geom = feature["geometry"]
        coords = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        properties.append({
            "car_code": feature["properties"]["codigo"],
            "area_ha": feature["properties"]["area"],
            "roi": ee.Geometry.MultiPolygon(coords),
        })
    return properties


@pytest.mark.parametrize("index", [0, 1])
def test_classify_pasture_on_the_fly_produces_plausible_result(index):
    prop = _load_test_properties()[index]

    result = classify_pasture_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])

    zarr_path, png_path = _cache_paths(prop["car_code"], result["pred_year"])
    assert zarr_path.exists(), "Cache zarr não foi criado"
    assert png_path.exists(), "Cache png não foi criado"

    assert 0 < result["area_pasto_ha"] <= prop["area_ha"], (
        f"Área de pasto ({result['area_pasto_ha']} ha) fora da faixa plausível "
        f"para uma propriedade de {prop['area_ha']} ha"
    )


def test_classify_pasture_on_the_fly_uses_cache_on_second_call():
    prop = _load_test_properties()[1]
    pred_year = _latest_mapbiomas_year() + 1

    zarr_path, png_path = _cache_paths(prop["car_code"], pred_year)
    if zarr_path.exists():
        shutil.rmtree(zarr_path)
    if png_path.exists():
        png_path.unlink()

    first = classify_pasture_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])
    assert first["cached"] is False
    assert zarr_path.exists() and png_path.exists()

    second = classify_pasture_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])
    assert second["cached"] is True
    assert second["area_pasto_ha"] == first["area_pasto_ha"]
