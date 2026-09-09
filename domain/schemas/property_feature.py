from uuid import uuid4
from typing import List, Optional

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


class SpatialFeatures(BaseModel):
    """Propriedades espaciais e territoriais de uma feição geográfica."""
    total_area: float = Field(
        ...,
        description="Área total da feição em hectares.",
        examples=[54.9041]
    )

    municipality: Optional[str] = Field(
        default=None,
        description="Nome do município onde a feição está localizada.",
        examples=["Jaraguá"]
    )

    coordinates: List[List[List[List[float]]]] = Field(
        ...,
        description="Coordenadas geográficas do polígono da feição (padrão GeoJSON)."
    )


class SicarMetadata(BaseModel):
    """Dados administrativos e de status do imóvel no SICAR."""

    tipo: str = Field(
        ...,
        description="Tipo do imóvel no SICAR (ex: IRU - Imóvel Rural).",
        examples=["IRU"]
    )

    status: str = Field(
        ...,
        description="Status do cadastro no SICAR (ex: AT para Ativo).",
        examples=["AT"]
    )

    availability_date: str = Field(
        ...,
        description="Data da última atualização ou disponibilidade do cadastro.",
        examples=["26/02/2021"]
    )

    creation_date: str = Field(
        ...,
        description="Data da criação original do cadastro no SICAR.",
        examples=["26/02/2021"]
    )


class PropertyFeature(BaseModel):
    """
    Contract shared by every registrable geographic feature.

    Concrete subclasses (e.g. RuralProperty, BufferedArea) must implement
    describe, get_coords and get_centroid, and expose an unique ``id``
    used by the tools to reference registered features. The ``feature_id``
    holds that id: it is auto-generated on registration and becomes the
    user-chosen name once the feature is named.
    """

    feature_id: Optional[str] = Field(
        default=None,
        description="Identificador único da feição; corresponde ao nome escolhido pelo usuário."
    )

    @property
    def id(self) -> str:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def get_coords(self):
        raise NotImplementedError

    def get_centroid(self) -> tuple[float, float]:
        raise NotImplementedError


class RuralProperty(PropertyFeature):
    car_code: str = Field(
        ...,
        pattern=r"^[A-Z]{2}-\d{7}-[A-Z0-9]{32}$",
        description="Código único do Cadastro Ambiental Rural (CAR).",
        examples=["GO-1111111-1111AAAA2222BBBB3333CCCC4444DDDD"]
    )

    spatial_features: SpatialFeatures = Field(
        ...,
        description="Objeto contendo as informações de área, município e coordenadas."
    )

    sicar_metadata: Optional[SicarMetadata] = Field(
        default=None,
        description="Objeto contendo os metadados administrativos do sistema SICAR."
    )


    @staticmethod
    def unify(rural_properties: List['RuralProperty']) -> 'RuralProperty':
        if len(rural_properties) == 1:
            return rural_properties[0]

        return RuralProperty(
            car_code=', '.join([prop.car_code for prop in rural_properties]),
            spatial_features=SpatialFeatures(
                total_area=sum([prop.spatial_features.total_area for prop in rural_properties]),
                coordinates=[coords[0] for prop in rural_properties for coords in prop.spatial_features.coordinates]
                )
            )

    @property
    def id(self) -> str:
        return self.feature_id or self.car_code

    def describe(self):
        return (
            f"Código CAR: {self.car_code}, "
            f"Área: {self.spatial_features.total_area} ha."
            )

    def get_coords(self):
        return self.spatial_features.coordinates

    def get_centroid(self) -> tuple[float, float]:
        return _compute_area_weighted_centroid(self.get_coords())

    def __str__(self):
        return f"ID: {self.id}, Código CAR: {self.car_code}."


class BufferedArea(PropertyFeature):
    """
    Área circular gerada a partir de um raio (buffer) ao redor de um ponto
    fornecido pelo usuário, em vez de um polígono de CAR.
    """

    feature_id: Optional[str] = Field(
        default_factory=lambda: uuid4().hex[:12],
        description="Identificador único da área; torna-se o nome escolhido pelo usuário.",
        examples=["a1b2c3d4e5f6"]
    )

    radius: float = Field(
        ...,
        gt=0,
        description="Raio do buffer em metros.",
        examples=[200]
    )

    center: tuple[float, float] = Field(
        ...,
        description="Coordenada central do buffer no formato (latitude, longitude).",
        examples=[(-15.7939, -49.4785)]
    )

    spatial_features: SpatialFeatures = Field(
        ...,
        description="Objeto contendo as informações de área e coordenadas do polígono do buffer."
    )


    @property
    def id(self) -> str:
        return self.feature_id

    def describe(self):
        return (
            f"Identificador: {self.id}, "
            f"Raio: {self.radius} m, "
            f"Área: {self.spatial_features.total_area} ha."
            )

    def get_coords(self):
        return self.spatial_features.coordinates

    def get_centroid(self) -> tuple[float, float]:
        return self.center

    def __str__(self):
        return f"ID: {self.id}, Raio: {self.radius} m."


def validate_feature_record(record: dict) -> PropertyFeature:
    """
    Rebuilds the correct PropertyFeature subclass from a stored record dict.

    Dispatches on the presence of discriminating keys: ``car_code`` maps to a
    RuralProperty, ``radius``/``center`` maps to a BufferedArea.
    """
    if "car_code" in record:
        return RuralProperty.model_validate(record)
    if "radius" in record or "center" in record:
        return BufferedArea.model_validate(record)

    raise ValueError(
        f"Record does not match any known PropertyFeature type: {list(record.keys())}"
    )