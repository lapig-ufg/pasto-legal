"""Conversion of geospatial documents to a single GeoJSON geometry and
construction of the registration ``Feature`` objects from it.

This module is intentionally free of Earth Engine dependencies so it can be
unit-tested hermetically. It handles the user-facing intake formats:

    - ``.zip`` (shapefile or any vector file inside)
    - ``.rar`` (shapefile or any vector file inside)
    - ``.kmz`` / ``.kml``
    - ``.geojson`` / ``.json`` (pass-through)

The output is always a GeoJSON ``FeatureCollection`` with a single feature
whose geometry is a ``Polygon`` (one polygon) or ``MultiPolygon`` (several
polygons), reprojected to EPSG:4326.

External interface:
    convert_geo_file_to_geojson  -- bytes of any supported file to GeoJSON bytes
    build_features_from_geojson  -- GeoJSON to (rural_property, paddocks)
    resolve_geo_filename         -- filename with a supported extension (sniffing)
    save_debug_json              -- best-effort debug dump under tmp/ (dev only)
    GeoFileError                 -- user-facing conversion failure
    UnsupportedFormatError       -- not a geo-intake format (silently ignorable)
"""

import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Union

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

from agno.utils.log import log_error, log_warning

from app.schemas.feature import Feature

_HECTARES_PER_SQUARE_METER = 1.0 / 10_000.0
_WGS84_EPSG = 4326

# Extensions accepted at intake and converted here.
SUPPORTED_EXTENSIONS = {".zip", ".rar", ".kmz", ".kml", ".geojson", ".json"}

# Vector extensions looked up inside archives.
_ARCHIVE_VECTOR_EXTENSIONS = {".shp", ".kml", ".geojson", ".json", ".gpkg"}


class GeoFileError(ValueError):
    """Raised when a supported file cannot be converted to a usable GeoJSON."""


class UnsupportedFormatError(GeoFileError):
    """Raised when the file format is not a supported geo-intake format."""


_DEBUG_DIR = Path.cwd() / "tmp" / "geojson_debug"


def debug_enabled() -> bool:
    """Whether the geojson debug dumps are enabled (non-production env)."""
    return os.getenv("APP_ENV", "").lower() in ("development", "dev", "stagging", "staging")


def save_debug_json(payload: Union[bytes, str, dict], label: str) -> Path | None:
    """Saves a GeoJSON payload under ``tmp/geojson_debug`` for debugging.

    Best-effort: any failure only logs a warning and never breaks the flow.
    Disabled outside development/staging environments.

    Args:
        payload: Raw bytes, string or parsed mapping to write.
        label: Short description included in the filename.

    Returns:
        The written path, or None when disabled or on failure.
    """
    if not debug_enabled():
        return None

    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        if isinstance(payload, dict):
            text = json.dumps(payload, ensure_ascii=False)
        elif isinstance(payload, (bytes, bytearray)):
            text = bytes(payload).decode("utf-8", errors="replace")
        else:
            text = str(payload)

        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "geojson"
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_label}.json"
        path = _DEBUG_DIR / filename
        path.write_text(text, encoding="utf-8")
        return path
    except Exception as error:  # pragma: no cover - defensive
        log_warning(f"geojson_io: failed to save debug json ({label}): {error}")
        return None


_ZIP_MAGIC = b"PK\x03\x04"
_RAR_MAGIC = b"Rar!\x1a\x07"


def _sniff_extension(content: bytes) -> str | None:
    """Detects a supported geo extension from the file magic bytes."""
    if content.startswith(_ZIP_MAGIC):
        return ".zip"
    if content.startswith(_RAR_MAGIC):
        return ".rar"
    head = content[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<kml"):
        return ".kml"
    if head.startswith(b"{") or head.startswith(b"["):
        return ".geojson"
    return None


def resolve_geo_filename(filename: str, content: bytes) -> str:
    """Returns a filename with a supported extension, sniffing when needed."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return filename

    sniffed = _sniff_extension(content)
    if sniffed is None:
        return filename

    stem = Path(filename).stem if filename else "upload"
    return f"{stem}{sniffed}"


# =====================================================================
# Reading and normalization
# =====================================================================


def _polygon_parts(geometry) -> List[Polygon]:
    """Recursively extracts the polygonal parts of a shapely geometry."""
    if geometry is None or geometry.is_empty:
        return []

    geom_type = geometry.geom_type
    if geom_type == "Polygon":
        return [geometry]
    if geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geom_type == "GeometryCollection":
        parts: List[Polygon] = []
        for sub_geometry in geometry.geoms:
            parts.extend(_polygon_parts(sub_geometry))
        return parts
    return []


def _safe_polygons(geometry) -> List[Polygon]:
    """Returns the polygonal parts of ``geometry``, repairing invalid shapes.

    Repair is applied to each part individually. Calling ``make_valid`` on a
    whole MultiPolygon whose parts overlap (a common case for adjacent
    paddocks) would merge them into a single geometry and lose the paddock
    boundaries, so every part is validated on its own.
    """
    try:
        if geometry is None or geometry.is_empty:
            return []

        parts: List[Polygon] = []
        for part in _polygon_parts(geometry):
            if part.is_valid:
                parts.append(part)
                continue
            try:
                parts.extend(_polygon_parts(shapely.make_valid(part)))
            except Exception as error:  # pragma: no cover - defensive
                log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return parts
    except Exception as error:  # pragma: no cover - defensive
        log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return []


def _read_layers(path: Path, driver: str | None = None) -> List[gpd.GeoDataFrame]:
    """Reads every vector layer of ``path`` (KML folders become layers)."""
    dataframes: List[gpd.GeoDataFrame] = []
    try:
        layer_names = list(gpd.list_layers(path)["name"])
    except Exception:
        layer_names = [None]

    for layer_name in layer_names:
        try:
            kwargs = {"driver": driver} if driver else {}
            if layer_name is not None:
                kwargs["layer"] = layer_name
            gdf = gpd.read_file(path, **kwargs)
        except Exception as error:
            log_warning(f"geojson_io: failed reading layer {layer_name} of {path.name}: {error}")
            continue

        if gdf is None or gdf.empty:
            continue
        dataframes.append(gdf)

    if not dataframes:
        raise GeoFileError(
            f"Não foi possível ler nenhuma camada do arquivo {path.name}. "
            "Verifique se o arquivo está íntegro."
        )
    return dataframes


def _read_vector_file(path: Path) -> List[gpd.GeoDataFrame]:
    """Reads a single vector file, choosing the driver by extension."""
    suffix = path.suffix.lower()

    if suffix == ".kmz":
        return _read_layers(path, driver="LIBKML")
    if suffix == ".kml":
        try:
            return _read_layers(path, driver="LIBKML")
        except GeoFileError:
            return _read_layers(path, driver="KML")
    return _read_layers(path)


def _extract_archive(content: bytes, filename: str, destination: Path) -> None:
    """Extracts a zip/rar archive into ``destination``."""
    suffix = Path(filename).suffix.lower()

    if suffix == ".zip":
        archive_path = destination / filename
        archive_path.write_bytes(content)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(destination)
        except zipfile.BadZipFile as error:
            raise GeoFileError(
                "O arquivo .zip enviado é inválido ou está corrompido."
            ) from error
        return

    try:
        import rarfile
    except ImportError as error:  # pragma: no cover - dependency check
        raise GeoFileError(
            "O suporte a arquivos .rar não está disponível no servidor no momento. "
            "Envie o arquivo como .zip ou .kmz."
        ) from error

    archive_path = destination / filename
    archive_path.write_bytes(content)
    try:
        with rarfile.RarFile(archive_path) as archive:
            archive.extractall(destination)
    except rarfile.RarCannotExec as error:
        raise GeoFileError(
            "Não foi possível extrair o arquivo .rar: o extrator não está instalado "
            "no servidor. Envie o arquivo como .zip ou .kmz."
        ) from error
    except Exception as error:
        raise GeoFileError(
            f"Não foi possível extrair o arquivo .rar. Verifique se ele está íntegro. "
            f"Detalhes: {error}"
        ) from error


def _collect_dataframes(content: bytes, filename: str, workdir: Path) -> List[gpd.GeoDataFrame]:
    """Loads all vector dataframes contained in the uploaded file."""
    suffix = Path(filename).suffix.lower()

    if suffix in (".zip", ".rar"):
        archive_dir = workdir / "archive"
        archive_dir.mkdir()
        _extract_archive(content, filename, archive_dir)

        vector_files = sorted(
            p for p in archive_dir.rglob("*") if p.suffix.lower() in _ARCHIVE_VECTOR_EXTENSIONS
        )
        if not vector_files:
            raise GeoFileError(
                "O arquivo enviado não contém nenhum shapefile (.shp), KML ou GeoJSON. "
                "Envie um .zip/.rar com os arquivos do shapefile."
            )

        dataframes: List[gpd.GeoDataFrame] = []
        for vector_file in vector_files:
            try:
                dataframes.extend(_read_vector_file(vector_file))
            except GeoFileError:
                continue
        if not dataframes:
            raise GeoFileError(
                "Não foi possível ler os arquivos vetoriais contidos no arquivo enviado."
            )
        return dataframes

    file_path = workdir / filename
    file_path.write_bytes(content)
    return _read_vector_file(file_path)


def _normalize_layer(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reprojects to WGS84 and drops Z.

    Geometry validity is handled per-part by ``_safe_polygons`` (calling
    ``make_valid`` here on a whole MultiPolygon with overlapping parts would
    merge adjacent paddocks).
    """
    if gdf.crs is None:
        log_warning("geojson_io: arquivo sem sistema de referência; assumindo EPSG:4326")
        gdf = gdf.set_crs(_WGS84_EPSG)
    elif gdf.crs.to_epsg() != _WGS84_EPSG:
        gdf = gdf.to_crs(_WGS84_EPSG)

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf["geometry"] = gdf.geometry.apply(shapely.force_2d)
    return gdf


def convert_geo_file_to_geojson(content: bytes, filename: str) -> bytes:
    """Converts any supported geospatial document to a single-geometry GeoJSON.

    All polygonal parts found across every feature/layer are merged into one
    geometry: a ``Polygon`` when there is a single part, otherwise a
    ``MultiPolygon``.

    Args:
        content: Raw bytes of the uploaded file.
        filename: Original filename (used to detect the format).

    Returns:
        GeoJSON ``FeatureCollection`` bytes in EPSG:4326.

    Raises:
        GeoFileError: When the file cannot be read or contains no polygon.
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Formato não suportado ({suffix or 'desconhecido'}). "
            "Envie um arquivo .zip, .rar, .kmz, .kml ou .geojson."
        )

    with tempfile.TemporaryDirectory(prefix="geojson_io_") as tmp:
        dataframes = _collect_dataframes(content, filename, Path(tmp))

    polygons: List[Polygon] = []
    for gdf in dataframes:
        try:
            for geometry in _normalize_layer(gdf).geometry:
                polygons.extend(_safe_polygons(geometry))
        except Exception as error:
            log_error(f"geojson_io: failed processing layer of {filename}: {error}")

    if not polygons:
        raise GeoFileError(
            "Nenhum polígono foi encontrado no arquivo enviado. "
            "São aceitos apenas arquivos com polígonos (limites da propriedade ou piquetes)."
        )

    geometry: Union[Polygon, MultiPolygon]
    if len(polygons) == 1:
        geometry = polygons[0]
    else:
        geometry = MultiPolygon(polygons)

    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "source_file": filename,
                    "polygon_count": len(polygons),
                },
                "geometry": mapping(geometry),
            }
        ],
    }

    return json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")


# =====================================================================
# Feature construction
# =====================================================================


def _geometry_to_coords(geometry) -> List[List[List[List[float]]]]:
    """Converts a shapely (Multi)Polygon to the schema GeoJSON coordinate nesting."""

    def rings(polygon: Polygon) -> List[List[List[float]]]:
        result = [[[float(x), float(y)] for x, y in polygon.exterior.coords]]
        for interior in polygon.interiors:
            result.append([[float(x), float(y)] for x, y in interior.coords])
        return result

    if geometry.geom_type == "Polygon":
        return [rings(geometry)]
    return [rings(part) for part in geometry.geoms]


def _area_hectares(geometry) -> float:
    """Computes the area in hectares using a local UTM projection."""
    series = gpd.GeoSeries([geometry], crs=f"EPSG:{_WGS84_EPSG}")
    projected = series.to_crs(series.estimate_utm_crs())
    return round(float(projected.area.iloc[0]) * _HECTARES_PER_SQUARE_METER, 2)


def _extract_geometry(geojson: Union[bytes, str, dict]):
    """Extracts a shapely (Multi)Polygon from a GeoJSON payload."""
    if isinstance(geojson, (bytes, bytearray)):
        try:
            geojson = geojson.decode("utf-8")
        except UnicodeDecodeError as error:
            raise GeoFileError("O arquivo GeoJSON não está em UTF-8.") from error

    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError as error:
            raise GeoFileError(
                "O conteúdo GeoJSON recebido é inválido. "
                "Passe o conteúdo exato do arquivo enviado pelo usuário."
            ) from error

    if not isinstance(geojson, dict):
        raise GeoFileError("O conteúdo GeoJSON recebido é inválido.")

    geometries = []
    if geojson.get("type") == "FeatureCollection":
        geojson_features = geojson.get("features") or []
        geometries = [f.get("geometry") for f in geojson_features if isinstance(f, dict)]
    elif geojson.get("type") == "Feature":
        geometries = [geojson.get("geometry")]
    elif geojson.get("type") in ("Polygon", "MultiPolygon"):
        geometries = [geojson]

    polygons: List[Polygon] = []
    for geometry in geometries:
        if not geometry:
            continue
        try:
            polygons.extend(_safe_polygons(shapely.geometry.shape(geometry)))
        except Exception as error:
            log_warning(f"geojson_io: invalid GeoJSON geometry skipped ({error})")

    if not polygons:
        raise GeoFileError(
            "Nenhum polígono válido foi encontrado no GeoJSON recebido. "
            "Passe o conteúdo exato do arquivo enviado pelo usuário."
        )

    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def build_features_from_geojson(
    geojson: Union[bytes, str, dict],
) -> tuple[Feature, List[Feature]]:
    """Builds the rural property (and paddocks) from a GeoJSON geometry.

    A single polygon becomes one ``rural_property``. Several polygons become one
    ``paddock`` per polygon (ids ``Paddock_1..N``) plus one ``rural_property``
    that is the dissolve of all of them. Paddocks and property start with
    independent ids; the property id is a generated base id.

    Args:
        geojson: GeoJSON bytes, string or parsed mapping.

    Returns:
        Tuple ``(rural_property, paddocks)``; ``paddocks`` is empty for a single
        polygon.

    Raises:
        GeoFileError: When no polygon is present.
    """
    geometry = _extract_geometry(geojson)

    if geometry.geom_type == "Polygon":
        property_feature = Feature(
            feature_id=Feature.generate_id(),
            coords=_geometry_to_coords(geometry),
            metadata=[],
            total_area=_area_hectares(geometry),
            region=None,
            feature_type="rural_property",
        )
        return property_feature, []

    parts = list(geometry.geoms)
    paddocks = [
        Feature(
            feature_id=f"Paddock_{index}",
            coords=_geometry_to_coords(part),
            metadata=[],
            total_area=_area_hectares(part),
            region=None,
            feature_type="paddock",
        )
        for index, part in enumerate(parts, start=1)
    ]

    dissolved = unary_union(parts)
    property_feature = Feature(
        feature_id=Feature.generate_id(),
        coords=_geometry_to_coords(dissolved),
        metadata=[],
        total_area=_area_hectares(dissolved),
        region=None,
        feature_type="rural_property",
    )

    return property_feature, paddocks
