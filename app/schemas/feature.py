from uuid import uuid4
from typing import List, Optional, Union

from pydantic import BaseModel, Field


def _compute_area_weighted_centroid(coords) -> tuple[float, float]:
    """
    Computes the area-weighted centroid of a GeoJSON MultiPolygon coordinate
    list using the shoelace formula.

    Args:
        coords: GeoJSON MultiPolygon nesting ([lon, lat] pairs).

    Returns:
        Tuple (latitude, longitude) of the centroid.
    """
    total_area = 0.0
    weighted_lat = 0.0
    weighted_lon = 0.0

    for polygon in coords:
        for ring in polygon:
            n = len(ring)
            signed_area = 0.0
            for i in range(n):
                lon1, lat1 = ring[i]
                lon2, lat2 = ring[(i + 1) % n]
                signed_area += (lon1 * lat2 - lon2 * lat1)
            signed_area /= 2.0

            if signed_area == 0.0:
                continue

            cx = 0.0
            cy = 0.0
            for i in range(n):
                lon1, lat1 = ring[i]
                lon2, lat2 = ring[(i + 1) % n]
                cross = (lon1 * lat2 - lon2 * lat1)
                cx += (lon1 + lon2) * cross
                cy += (lat1 + lat2) * cross

            cx /= (6.0 * signed_area)
            cy /= (6.0 * signed_area)

            ring_area = abs(signed_area)
            weighted_lat += cy * ring_area
            weighted_lon += cx * ring_area
            total_area += ring_area

    if total_area == 0.0:
        pts = []
        for polygon in coords:
            for ring in polygon:
                pts.extend(ring)
        if not pts:
            raise ValueError("Feature coordinates are empty.")
        lat = sum(p[1] for p in pts) / len(pts)
        lon = sum(p[0] for p in pts) / len(pts)
        return lat, lon

    return weighted_lat / total_area, weighted_lon / total_area


class FeatureMetadata(BaseModel):
    """A single arbitrary attribute attached to a feature.

    Any feature type can carry any key/value pair (e.g. ``car_code``,
    ``radius``, ``tipo``, ``status``), so new feature types never require
    new schemas.
    """

    key: str = Field(
        ...,
        description="Nome do atributo (ex: car_code, radius, tipo, status).",
        examples=["car_code"]
    )

    value: Union[str, float, int] = Field(
        ...,
        description="Valor do atributo.",
        examples=["GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"]
    )


class Feature(BaseModel):
    """General schema representing any geographic feature in the system.

    Every registrable feature — rural properties (SICAR), buffered areas or
    any future type — is represented by this single model. Type-specific
    data lives in the free-form ``metadata`` list; ``feature_type`` is a
    plain field holding the neutral key identifying the type (never
    localized).

    The ``feature_id`` is the unique reference used by the tools: it is set
    to a default by the registration pipeline (car_code for rural
    properties, generated id for buffers) and becomes the user-chosen name
    once the feature is named.
    """

    feature_id: Optional[str] = Field(
        default=None,
        description="Identificador único da feição; corresponde ao nome escolhido pelo usuário."
    )

    coords: List[List[List[List[float]]]] = Field(
        ...,
        description="Coordenadas geográficas da feição (padrão GeoJSON MultiPolygon)."
    )

    metadata: List[FeatureMetadata] = Field(
        default_factory=list,
        description="Atributos específicos do tipo de feição (pares chave/valor)."
    )

    total_area: float = Field(
        ...,
        description="Área total da feição em hectares.",
        examples=[54.9041]
    )

    region: Optional[str] = Field(
        default=None,
        description="Região onde a feição está localizada (ex: município).",
        examples=["Jaraguá"]
    )

    feature_type: str = Field(
        ...,
        description="Chave neutra identificando o tipo da feição (ex: rural_property, buffer_area)."
    )

    @property
    def id(self) -> Optional[str]:
        return self.feature_id

    def get_metadata(self, key: str, default=None):
        """Returns the metadata value for ``key``, or ``default`` when absent."""
        for entry in self.metadata:
            if entry.key == key:
                return entry.value
        return default

    def get_coords(self) -> List[List[List[List[float]]]]:
        return self.coords

    def get_centroid(self) -> tuple[float, float]:
        return _compute_area_weighted_centroid(self.coords)

    def describe(self) -> str:
        details = ", ".join(f"{entry.key}: {entry.value}" for entry in self.metadata)
        region = f", Região: {self.region}" if self.region else ""
        metadata = f", {details}" if details else ""
        return (
            f"Identificador: {self.id}, "
            f"Tipo: {self.feature_type}, "
            f"Área: {self.total_area} ha.{region}{metadata}"
        )

    def __str__(self):
        return self.describe()

    @staticmethod
    def generate_id() -> str:
        """Generates a short unique id for unnamed features."""
        return uuid4().hex[:12]

    @staticmethod
    def unify(features: List['Feature']) -> Optional['Feature']:
        """Merges multiple features of the same type into a single feature.

        Coords polygons and areas are combined; metadata keys shared by all
        features are joined with ``", "``; ``feature_id``/``region`` of the
        first feature are kept. Returns None when ``features`` is empty.
        """
        if not features:
            return None

        coords: List[List[List[List[float]]]] = []
        metadata: dict = {}
        for feature in features:
            coords.extend(feature.coords)
            for entry in feature.metadata:
                if entry.key not in metadata:
                    metadata[entry.key] = []
                if entry.value not in metadata[entry.key]:
                    metadata[entry.key].append(entry.value)

        return Feature(
            feature_id=features[0].feature_id,
            coords=coords,
            metadata=[
                FeatureMetadata(key=key, value=", ".join(str(v) for v in values))
                for key, values in metadata.items()
            ],
            total_area=sum(feature.total_area for feature in features),
            region=features[0].region,
            feature_type=features[0].feature_type,
        )


class RegisteredFeatures(BaseModel):
    """All features registered in the system for the current session."""

    features: List[Feature] = Field(
        default_factory=list,
        description="Feições registradas no sistema."
    )

    def build_prompt(self) -> str:
        """Builds a prompt describing every registered feature, clustered
        by feature type inside ``<feature_type>...</feature_type>`` tags."""

        if not self.features:
            return ""

        clusters: dict[str, List[str]] = {}
        for feature in self.features:
            clusters.setdefault(feature.feature_type, []).append(feature.describe())

        parts: List[str] = []
        for feature_type, descriptions in clusters.items():
            body = "\n".join(f"  - {description}" for description in descriptions)
            parts.append(f"<{feature_type}>\n{body}\n</{feature_type}>")

        return "\n".join(parts)