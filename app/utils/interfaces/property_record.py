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
    municipality: str = Field(
        ..., 
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

    sicar_metadata: SicarMetadata = Field(
        ..., 
        description="Objeto contendo os metadados administrativos do sistema SICAR."
    )

    def __str__(self):
        return (
            f"Código CAR: {self.car_code},"
            f"Área: {self.spatial_features.total_area} ha,"
            f"Município: {self.spatial_features.municipality}"
            )
    

class PropertyRecord(BaseModel):
    id: Optional[str] = Field(
        description="Identificador único da propriedade rural.",
        default_factory=lambda: f"{str(uuid4())}"
    )

    nickname: Optional[str] = Field(
        default=None,
        description="Nome escolhido para identificar a propriedade rural."
    )

    properties: List[RuralProperty] = Field(
        ...,
        description="Lista de propriedades rurais. "
    )


    def get_coords(self):
        return [prop.spatial_features.coordinates[0] for prop in self.properties]


    def __str__(self):
        car_codes = ', '.join([prop.car_code for prop in self.properties])

        return f"ID: {self.id}, Nome: {self.nickname}, Códigos CAR: {car_codes}"