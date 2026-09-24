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


# UserPersona fields default to a sentinel string instead of None, so a
# persona built from the schema alone looks "informed". Both the onboarding
# gate and the welcoming agent must treat the sentinel as missing.
UNKNOWN_PERSONA_VALUES = {
    UserPersona.model_fields["name"].default,
    UserPersona.model_fields["role"].default,
}


def is_persona_field_informed(value) -> bool:
    """True when a persona field holds an actual value (not None/sentinel)."""
    return bool(value) and value not in UNKNOWN_PERSONA_VALUES


def is_persona_complete(persona) -> bool:
    """True when both the name and the role are informed (not sentinel)."""
    persona = persona or {}
    return (
        is_persona_field_informed(persona.get("name"))
        and is_persona_field_informed(persona.get("role"))
    )


class PersonaUpdate(BaseModel):
    """Structured output do agente gerenciador de persona.

    Representa as mudanças que o agente deseja aplicar na persona do usuário.
    Apenas campos preenchidos serão atualizados.

    Nome e função NÃO aparecem aqui de propósito: são identidade declarada
    pelo usuário no onboarding e só mudam a pedido explícito dele, pelas tools
    `update_persona_name` e `update_persona_role`. Este agente roda sozinho a
    cada resposta e trabalha por dedução — dedução não sobrescreve declaração.
    """
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