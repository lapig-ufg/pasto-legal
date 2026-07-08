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
            - Nome: {self.name}
            - Profissão: {self.role}
            - Regionalidade: {self.regionality}{preferences_text}
        """).strip()


class PersonaUpdate(BaseModel):
    """Structured output from the persona manager agent.

    Represents the changes the agent wants to apply to the user's persona.
    Only non-None fields will be applied.
    """

    name: Optional[str] = Field(
        default=None,
        description="Updated name for the user, or None to keep current.",
    )
    role: Optional[str] = Field(
        default=None,
        description="Updated role ('Produtor' or 'Tecnico'), or None to keep current.",
    )
    regionality: Optional[str] = Field(
        default=None,
        description="Updated city/state/region, or None to keep current.",
    )
    preferences: List[Preferences] = Field(
        default_factory=list,
        description="List of preferences to add or update in the user persona. "
        "Use an existing key to update, or a new key to create.",
    )