"""
Teste de integração real (GEE) da biomassa Time2Graze mascarada pela classificação de
pastagem on-the-fly, em vez do mapa estático do Global Pasture Watch.

Precisa de um `.env` real (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE, APP_ENV).

    .venv/bin/python -m pytest tests/ee_scripts/test_biomass_on_the_fly_mask.py -v
"""
import json
from pathlib import Path

import ee
import pytest

from domain.services.geospatial.gee import get_biomass, retrieve_gpw_biomass_image, retrieve_t2g_biomass_image
from domain.services.geospatial.pasture_classification import get_on_the_fly_pasture_mask

_MOCK_PATH = Path(__file__).resolve().parents[2] / "domain/utils/mocks/new_property_mock.json"

pytestmark = pytest.mark.integration

# Referência de agosto/2026 (a biomassa acumula o mês anterior), período com imagens Time2Graze.
_MONTH, _YEAR = 9, 2026


def _first_property_coords():
    geom = json.loads(_MOCK_PATH.read_text())["features"][0]["geometry"]
    return geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


def test_on_the_fly_mask_is_a_binary_image_over_the_property():
    roi = ee.Geometry.MultiPolygon(_first_property_coords())

    mask = get_on_the_fly_pasture_mask(roi)

    assert mask is not None
    values = mask.reduceRegion(ee.Reducer.minMax(), roi, scale=10, maxPixels=1e13).getInfo()
    assert set(values.values()) <= {0, 1}


def test_time2graze_biomass_with_the_on_the_fly_mask_differs_from_the_static_gpw_mask():
    roi = ee.Geometry.MultiPolygon(_first_property_coords())
    mask = get_on_the_fly_pasture_mask(roi)
    assert mask is not None

    static = get_biomass(roi, _MONTH, _YEAR)
    on_the_fly = get_biomass(roi, _MONTH, _YEAR, pasture_mask=mask)

    assert static.period == "mensal"
    assert on_the_fly.period == "mensal" and on_the_fly.observation_year == static.observation_year
    assert on_the_fly.amount.value > 0
    assert on_the_fly.amount.value != static.amount.value


def test_biomass_map_accepts_the_on_the_fly_mask():
    coords = _first_property_coords()
    mask = get_on_the_fly_pasture_mask(ee.Geometry.MultiPolygon(coords))

    result = retrieve_t2g_biomass_image(coords, _MONTH, _YEAR, pasture_mask=mask)

    assert result is not None
    image, year, month = result
    assert image.size[0] > 0 and (year, month) == (2026, 8)


def test_gpw_biomass_map_renders_with_its_colorbar():
    assert retrieve_gpw_biomass_image(_first_property_coords()).size[0] > 0
