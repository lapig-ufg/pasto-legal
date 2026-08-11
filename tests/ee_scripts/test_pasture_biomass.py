"""
Teste de integração real (GEE + Xee) para a série histórica de biomassa de pastagem
(Global Pasture Watch).

`app/services/geospatial/gee.py` inicializa o Earth Engine na importação do módulo,
então este teste precisa de um `.env` real na raiz do projeto (GEE_PROJECT,
GEE_SERVICE_ACCOUNT, GEE_KEY_FILE, APP_ENV) para rodar. `pasture_biomass.py` não
importa `gee.py` (de propósito, ver plano de biomassa histórica), então importamos
`gee` aqui só pelo efeito colateral de inicializar o Earth Engine — no app real isso
já acontece via `property_analyst_tools.py`, que importa os dois módulos.

    .venv/bin/python -m pytest tests/ee_scripts/test_pasture_biomass.py -v
"""
import json
import math
import shutil
from pathlib import Path

import ee
import pytest

import app.services.geospatial.gee  # noqa: F401 — inicializa o Earth Engine

from app.services.geospatial.pasture_biomass import (
    _latest_gpw_year,
    estimate_pasture_biomass_history,
)
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


def test_latest_gpw_year_is_plausible():
    year = _latest_gpw_year()
    assert 2000 <= year <= 2030


@pytest.mark.parametrize("index", [0, 1])
def test_estimate_pasture_biomass_history_produces_plausible_values(index):
    prop = _load_test_properties()[index]

    result = estimate_pasture_biomass_history(roi=prop["roi"], car_code=prop["car_code"])

    latest_year = _latest_gpw_year()
    zarr_path, png_path = _cache_paths(prop["car_code"], f"history_{latest_year}", kind="biomass")
    assert Path(zarr_path).exists(), "Cache zarr não foi criado"
    assert Path(png_path).exists(), "Cache png não foi criado"

    yearly_avg = result["yearly_avg_t_ha"]
    assert result["history_start_year"] == 2000
    assert result["history_end_year"] == latest_year
    assert len(yearly_avg) == latest_year - 2000 + 1

    plausible_values = [value for value in yearly_avg.values() if not math.isnan(value)]
    assert plausible_values, "Nenhum ano com pastagem mapeada — resultado suspeito"
    assert all(0 <= value <= 30 for value in plausible_values), (
        f"Valores fora da faixa plausível (0-30 t/ha/ano): {plausible_values}"
    )


def test_estimate_pasture_biomass_history_uses_cache_on_second_call():
    prop = _load_test_properties()[1]
    latest_year = _latest_gpw_year()

    zarr_path, png_path = _cache_paths(prop["car_code"], f"history_{latest_year}", kind="biomass")
    if Path(zarr_path).exists():
        shutil.rmtree(zarr_path)
    if Path(png_path).exists():
        Path(png_path).unlink()

    first = estimate_pasture_biomass_history(roi=prop["roi"], car_code=prop["car_code"])
    assert first["cached"] is False
    assert Path(zarr_path).exists() and Path(png_path).exists()

    second = estimate_pasture_biomass_history(roi=prop["roi"], car_code=prop["car_code"])
    assert second["cached"] is True
    assert second["yearly_avg_t_ha"].keys() == first["yearly_avg_t_ha"].keys()
    for year, first_value in first["yearly_avg_t_ha"].items():
        second_value = second["yearly_avg_t_ha"][year]
        if math.isnan(first_value):
            assert math.isnan(second_value)
        else:
            assert second_value == first_value
