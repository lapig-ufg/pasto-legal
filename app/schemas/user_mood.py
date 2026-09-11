from typing import Optional
from pydantic import BaseModel, Field


class Effectiveness(BaseModel):
    level: int = Field(
        description="Nível de satisfação do usuário (1 a 5, onde 1 é muito frustrado e 5 é muito satisfeito)",
        ge=1,
        le=5
    )
    level_message: str = Field(
        description="Mensagem descritiva ou justificativa do nível de satisfação (ex: 'Usuário demonstrou ironia e insatisfação com a resposta anterior')"
    )


class Remediation(BaseModel):
    effectiveness: Effectiveness = Field(
        description="Avaliação da eficácia e humor atual do usuário durante o processo de remediação"
    )
    new_message: Optional[str] = Field(
        default=None,
        description="A nova mensagem reformulada ou proposta de solução apresentada ao usuário"
    )
    old_message: Optional[str] = Field(
        default=None,
        description="A mensagem ou contexto anterior que gerou o conflito/frustração"
    )


class UserMood(BaseModel):
    satisfaction: Effectiveness = Field(
        description="Estado de satisfação e humor geral do usuário no momento atual"
    )
    remediation: Optional[Remediation] = Field(
        default=None,
        description="Dados sobre a tentativa de contornar a frustração do usuário, se aplicável"
    )