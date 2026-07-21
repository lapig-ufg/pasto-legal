import textwrap
from typing import List, Optional
from pydantic import BaseModel, Field


class CommunicationPreference(BaseModel):
    key: str = Field(
        description=(
            "A chave da preferência de comunicação/interação com o usuário "
            "(ex: 'tom_de_voz', 'tamanho_resposta', 'formato_explicacao', 'uso_emojis'). "
        )
    )
    description: str = Field(
        description=(
            "A especificação de como o agente deve se comportar ao responder "
            "(ex: 'Prefere respostas em tópicos e bem diretas', 'Gosta de tom informal e descontraído')."
        )
    )


class UserPersona(BaseModel):
    name: Optional[str] = Field(
        default="Ainda não conhecido",
        description="Nome do usuário."
    )
    role: Optional[str] = Field(
        default="Ainda não conhecido",
        description="O papel ou profissão do usuário (ex: 'Produtor', 'Técnico')."
    )
    regionality: Optional[str] = Field(
        default="Ainda não conhecido",
        description="Localização regional, cidade ou estado do usuário."
    )
    communication_preferences: List[CommunicationPreference] = Field(
        default_factory=list,
        description="Lista de preferências exclusivamente focadas em como o agente deve interagir e formatar as respostas."
    )

def __str__(self) -> str:
        preferences_text = "".join(
            f"\n- {pref.key.title()}: {pref.description}" for pref in self.communication_preferences
        )

        return textwrap.dedent(f"""
            - Nome: {self.name}
            - Profissão: {self.role}
            - Regionalidade: {self.regionality}{preferences_text}
        """).strip()


class PersonaUpdate(BaseModel):
    """Structured output do agente gerenciador de persona.

    Representa as mudanças que o agente deseja aplicar na persona do usuário.
    Apenas campos preenchidos serão atualizados.
    """

    name: Optional[str] = Field(
        default=None,
        description="Nome atualizado do usuário, ou None para manter o atual.",
    )
    role: Optional[str] = Field(
        default=None,
        description="Cargo ou papel atualizado ('Produtor' ou 'Técnico'), ou None para manter o atual.",
    )
    regionality: Optional[str] = Field(
        default=None,
        description="Cidade/estado/região atualizada, ou None para manter o atual.",
    )
    communication_preferences: List[CommunicationPreference] = Field(
        default_factory=list,
        description=(
            "Lista de preferências EXCLUSIVAMENTE de estilo de comunicação, formato de resposta "
            "ou tom de voz a serem adicionadas ou atualizadas."
        ),
    )