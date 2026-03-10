from typing import List
from pydantic import BaseModel, Field


class AreaInfo(BaseModel):
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


class SicarInfo(BaseModel):
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


class PropertyRecord(BaseModel):
    """
    Modelo Pydantic para representar os dados consolidados do Imóvel Rural.
    """
    code: str = Field(
        ..., 
        pattern=r"^[A-Z]{2}-\d{7}-[A-Z0-9]{32}$",
        description="Código único do Cadastro Ambiental Rural (CAR).",
        examples=["GO-5211800-987B29E7E47A4454BAEF582557AB89F3"]
    )
    area_info: AreaInfo = Field(
        ..., 
        description="Objeto contendo as informações de área, município e coordenadas."
    )
    sicar_info: SicarInfo = Field(
        ..., 
        description="Objeto contendo os metadados administrativos do sistema SICAR."
    )