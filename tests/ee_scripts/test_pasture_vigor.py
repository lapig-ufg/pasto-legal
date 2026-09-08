"""
Teste de integração real (GEE + Xee) para o vigor de pastagem on-the-fly.

Ver `test_pasture_biomass.py` para o motivo do import de `app.services.geospatial.gee`
(inicializa o Earth Engine via `.env` real na raiz do projeto).

    .venv/bin/python -m pytest tests/ee_scripts/test_pasture_vigor.py -v
"""
import json
import shutil
from pathlib import Path

import ee
import pytest

import app.services.geospatial.gee  # noqa: F401 — inicializa o Earth Engine

from app.services.geospatial.pasture_vigor import _VIGOR_DICT, estimate_pasture_vigor_on_the_fly
from app.services.geospatial.pasture_cache import _cache_paths

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
def test_estimate_pasture_vigor_on_the_fly_produces_plausible_values(index):
    prop = _load_test_properties()[index]

    result = estimate_pasture_vigor_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])

    assert result["pred_year"] == result["train_year"] + 1
    assert result["calibration_status"] in {"calibrated", "fallback"}
    assert result["calibration_metric"] in {"amplitude", "mean_ndvi"}

    zarr_path, png_path = _cache_paths(prop["car_code"], result["pred_year"], kind="vigor")
    assert Path(zarr_path).exists(), "Cache zarr não foi criado"
    assert Path(png_path).exists(), "Cache png não foi criado"

    area_by_class = result["area_by_vigor_class_ha"]
    assert area_by_class, "Nenhuma área de pastagem mapeada — resultado suspeito"
    assert set(area_by_class.keys()) <= set(_VIGOR_DICT.values())
    assert all(area > 0 for area in area_by_class.values())
    assert sum(area_by_class.values()) <= prop["area_ha"] * 1.05  # tolerância de reprojeção/borda


def test_estimate_pasture_vigor_on_the_fly_uses_cache_on_second_call():
    prop = _load_test_properties()[1]

    result_probe = estimate_pasture_vigor_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])
    pred_year = result_probe["pred_year"]

    zarr_path, png_path = _cache_paths(prop["car_code"], pred_year, kind="vigor")
    if Path(zarr_path).exists():
        shutil.rmtree(zarr_path)
    if Path(png_path).exists():
        Path(png_path).unlink()

    first = estimate_pasture_vigor_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])
    assert first["cached"] is False
    assert Path(zarr_path).exists() and Path(png_path).exists()

    second = estimate_pasture_vigor_on_the_fly(roi=prop["roi"], car_code=prop["car_code"])
    assert second["cached"] is True
    assert second["area_by_vigor_class_ha"] == first["area_by_vigor_class_ha"]
    assert second["calibration_status"] == first["calibration_status"]
