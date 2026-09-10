from typing import Optional
from pydantic import BaseModel, Field

class ProactiveSuggestion(BaseModel):
    main_response: str = Field(
        description="Texto principal contendo o diagnóstico ou resposta base."
    )
    proactive_suggestion: Optional[str] = Field(
        default=None,
        description="Pergunta instigante, CTA ou sugestão de continuidade."
    )