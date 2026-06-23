from typing import Literal

from agno.tools import tool
from agno.run import RunContext
from agno.tools.function import ToolResult

# TODO: Salvar na tabela UserProfiles do banco de dados.
@tool
def update_persona(
    run_context: RunContext,
    name: str | None = None,
    city: str | None = None,
    role: Literal["Produtor", "Técnico"] | None = None
    ):
    """
    Atualiza incrementalmente a persona (perfil) do usuário no estado da sessão.

    Esta ferramenta deve ser chamada de forma orgânica e gradual. 
    Use-a apenas quando o usuário fornecer alguma dessas informações durante a conversa. 
    
    Não force o usuário a responder tudo de uma vez e não invente dados. Se o usuário 
    mencionou apenas a cidade, passe apenas o parâmetro 'city'. O restante do perfil 
    será preenchido ao longo do tempo.

    Args:
        name (str | None): Nome do usuário (ex: "João", "Maria"). Passe apenas se informado.
        city (str | None): Cidade onde o usuário mora ou atua. Passe apenas se informada.
        role (Literal["Produtor", "Técnico"] | None): Papel profissional do usuário. 
            Escolha "Produtor" para produtores rurais/cultivadores ou "Técnico" para assistentes técnicos/agrônomos.
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})

    if name is not None:
        user_persona['name'] = name.title()

    if city is not None:
        user_persona['city'] = city.title()

    if role is not None:
        user_persona['role'] = role.capitalize()

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state

    return
