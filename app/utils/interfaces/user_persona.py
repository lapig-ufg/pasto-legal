import textwrap
from typing import List, Optional
from pydantic import BaseModel, Field


class Preferences(BaseModel):
    key: str = Field(description="A chave ou categoria da preferência (ex: 'hobbie', 'comida')")
    description: str = Field(description="A descrição detalhada da preferência")  # Corrigido 'FIeld'


class UserPersona(BaseModel):
    name: Optional[str] = Field(default="Desconhecido (Tente descobrir de forma sutíl)")
    role: Optional[str] = Field(default="Desconhecido (Tente descobrir de forma sutíl)")
    regionality: Optional[str] = Field(default="Desconhecida (Tente descobrir de forma sutíl)")
    
    preferences: List[Preferences] = Field(default_factory=list)

    def __str__(self) -> str:
        preferences_text = "".join(
            f"\n- {pref.key.title()}: {pref.description}" for pref in self.preferences
        )

        return textwrap.dedent(f"""
            <user-persona>
            - Nome: {self.name}
            - Profissão: {self.role}
            - Regionalidade: {self.regionality}{preferences_text}
            </user-persona>
        """).strip()