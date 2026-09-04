from uuid import uuid4
from typing import List, Optional
from pydantic import BaseModel, Field


class SpatialFeatures(BaseModel):
    """Propriedades espaciais e territoriais do imóvel."""
    total_area: float = Field(
        ..., 
        description="Área total do imóvel rural.", 
        examples=[54.9041]
    )

    municipality: Optional[str] = Field(
        default=None,
        description="Nome do município onde o imóvel está localizado.", 
        examples=["Jaraguá"]
    )

    coordinates: List[List[List[List[float]]]] = Field(
        ..., 
        description="Coordenadas geográficas do polígono do imóvel (padrão GeoJSON)."
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
        description="Data de criação original do cadastro no SICAR.", 
        examples=["26/02/2021"]
    )


class RuralProperty(BaseModel):
    nickname: Optional[str] = Field(
        default=None,
        description="Nome escolhido para identificar a propriedade rural."
    )
        
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
    def unify(rural_properties: List['RuralProperty'], nickname: str = None) -> 'RuralProperty':
        if len(rural_properties) == 1:
            return rural_properties[0]

        return RuralProperty(
            nickname=nickname,
            car_code=', '.join([prop.car_code for prop in rural_properties]),
            spatial_features=SpatialFeatures(
                total_area=sum([prop.spatial_features.total_area for prop in rural_properties]),
                coordinates=[coords[0] for prop in rural_properties for coords in prop.spatial_features.coordinates]
                )
            )

    def describe(self):
        return (
            f"Código CAR: {self.car_code}, "
            f"Área: {self.spatial_features.total_area} ha."
            )
    
    def get_coords(self):
        return self.spatial_features.coordinates

    def get_centroid(self) -> tuple[float, float]:
        """
        Computes the area-weighted centroid of the rural property polygon.

        Returns:
            Tuple (latitude, longitude) of the centroid.
        """
        coords = self.get_coords()
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
                raise ValueError("Property coordinates are empty.")
            lat = sum(p[1] for p in pts) / len(pts)
            lon = sum(p[0] for p in pts) / len(pts)
            return lat, lon

        return weighted_lat / total_area, weighted_lon / total_area

    def __str__(self):
        return (
            f"Nickname: {self.nickname}, "
            f"Código CAR: {self.car_code}."
            )