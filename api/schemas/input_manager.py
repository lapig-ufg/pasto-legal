from typing import Optional
from pydantic import BaseModel, Field


class InputManager(BaseModel):
    summary: Optional[str] = Field(
        default=None,
        description="Resumo acumulado do contexto da conversa."
    )
    runs_count: int = Field(
        default=0,
        description="Contador de execuções desde o último resumo."
    )