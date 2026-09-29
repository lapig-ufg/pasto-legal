"""
Testes do passo de pré-processamento de entrada para arquivos geoespaciais.

`app/steps/input_step.py` importa `app.agents` (que inicializa o Earth Engine na
importação), então este teste precisa de um `.env` real na raiz do projeto.

    .venv/bin/python -m pytest tests/steps/test_input_step_geo.py -v
"""
import json
import os
import tempfile
import zipfile

import geopandas as gpd
from shapely.geometry import Polygon
from agno.media import File
from agno.workflow.types import StepInput

from app.steps.input_step import _input_processing_executor


def _zipped_shapefile_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        gdf = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
            crs="EPSG:4326",
        )
        gdf.to_file(os.path.join(tmp, "layer.shp"))

        zip_path = os.path.join(tmp, "shape.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name in os.listdir(tmp):
                if name.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                    archive.write(os.path.join(tmp, name), name)

        return open(zip_path, "rb").read()


def test_geo_file_is_converted_and_attached_as_json():
    step_input = StepInput(
        input="Quero registrar minha propriedade",
        files=[File(content=_zipped_shapefile_bytes(), name="shape.zip")],
    )

    output = _input_processing_executor(step_input)

    assert output.files and len(output.files) == 1
    converted = output.files[0]
    assert converted.format == "geojson"
    assert converted.mime_type == "application/json"
    assert converted.name == "shape.json"
    assert json.loads(converted.content.decode())["type"] == "FeatureCollection"
    # The raw document must not be carried over.
    assert all(file.format != "zip" for file in output.files)


def test_invalid_geo_file_appends_error_note_and_no_file():
    step_input = StepInput(
        input="Segue o arquivo",
        files=[File(content=b"not a geo file", name="shape.zip")],
    )

    output = _input_processing_executor(step_input)

    assert output.files is None
    assert output.content
    assert "[ARQUIVO GEOESPACIAL]" in output.content


def test_non_geo_file_is_ignored():
    step_input = StepInput(
        input="Olá",
        files=[File(content=b"%PDF-1.4 ...", name="document.pdf")],
    )

    output = _input_processing_executor(step_input)

    assert output.files is None
    assert output.content == "Olá"


def test_zip_without_filename_is_detected_by_magic_bytes():
    step_input = StepInput(
        input="",
        files=[File(content=_zipped_shapefile_bytes())],
    )

    output = _input_processing_executor(step_input)

    assert output.files and output.files[0].format == "geojson"
