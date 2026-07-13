from typing import Literal, List, Dict
import textwrap

from agno.tools import tool
from agno.run import RunContext
from agno.tools.function import ToolResult


# =====================================================================
# TOOLS PARA ATRIBUTOS PRINCIPAIS
# =====================================================================

@tool
def update_persona_name(name: str, run_context: RunContext) -> str:
    """
    Atualiza organicamente o nome da persona (perfil) do usuário no estado da sessão.

    Use esta ferramenta apenas quando o usuário informar ou confirmar o seu nome 
    durante a conversa de forma natural.

    Args:
        name (str): Nome próprio do usuário (ex: "João", "Maria").
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})

    user_persona['name'] = name.strip().title()

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Nome atualizado com sucesso para: {user_persona['name']}"


@tool
def update_persona_role(role: Literal["Produtor", "Técnico"], run_context: RunContext) -> str:
    """
    Atualiza organicamente o papel profissional da persona do usuário no estado da sessão.

    Use esta ferramenta quando identificar claramente se o usuário é um produtor rural
    ou um assistente técnico/agrônomo.

    Args:
        role (Literal["Produtor", "Técnico"]): O papel profissional identificado.
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})

    # Garante a formatação correta de acordo com o Literal recebido
    user_persona['role'] = role.strip().capitalize()

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Papel profissional atualizado com sucesso para: {user_persona['role']}"


@tool
def update_persona_region(regionality: str, run_context: RunContext) -> str:
    """
    Atualiza organicamente a regionalidade/localização da persona no estado da sessão.

    Use esta ferramenta quando o usuário mencionar a cidade, estado ou região onde atua.

    Args:
        regionality (str): Cidade, estado ou região do usuário (ex: "Sorriso - MT", "Sul de Minas").
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})

    user_persona['regionality'] = regionality.strip().title()

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Regionalidade atualizada com sucesso para: {user_persona['regionality']}"


# =====================================================================
# TOOLS PARA GERENCIAMENTO DE PREFERÊNCIAS
# =====================================================================

@tool
def create_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Adiciona uma nova preferência, interesse, hobbie ou comportamento descoberto sobre o usuário.

    Use esta ferramenta de forma sutil sempre que captar um gosto, rotina ou preferência do usuário.
    Evite duplicar chaves existentes. Se a chave já existir, use 'update_persona_preference'.

    Args:
        key (str): Uma palavra-chave curta em minúsculas identificando a categoria (ex: "cultura", "cafe", "horario_contato", "canal_favorito").
        description (str): Detalhes sobre o gosto ou comportamento do usuário naquela categoria.
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})
    
    if "preferences" not in user_persona or not isinstance(user_persona["preferences"], list):
        user_persona["preferences"] = []

    normalized_key = key.strip().lower()

    for pref in user_persona["preferences"]:
        if pref.get("key") == normalized_key:
            return f"A preferência '{key}' já existe. Use 'update_persona_preference' para modificá-la."

    user_persona["preferences"].append({
        "key": normalized_key,
        "description": description.strip()
    })

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Nova preferência registrada: {normalized_key.title()} -> {description}"


@tool
def update_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Atualiza uma preferência ou comportamento já existente na persona do usuário.

    Use esta ferramenta quando o usuário mudar de opinião ou trouxer novas informações 
    sobre um ponto que já havia sido mapeado anteriormente.

    Args:
        key (str): A palavra-chave exata da preferência a ser atualizada (ex: "cultura", "cafe").
        description (str): A nova descrição atualizada que substituirá a anterior.
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})
    preferences = user_persona.get("preferences", [])

    normalized_key = key.strip().lower()
    updated = False

    for pref in preferences:
        if pref.get("key") == normalized_key:
            pref["description"] = description.strip()
            updated = True
            break

    if not updated:
        return f"Não foi possível atualizar: A preferência com a chave '{key}' não foi encontrada."

    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Preferência '{normalized_key.title()}' atualizada com sucesso."


@tool
def remove_persona_preference(key: str, run_context: RunContext) -> str:
    """
    Remove uma preferência específica do perfil do usuário caso ela não seja mais válida.

    Args:
        key (str): A palavra-chave da preferência que deve ser removida.
    """
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", {})
    preferences = user_persona.get("preferences", [])

    normalized_key = key.strip().lower()
    
    initial_count = len(preferences)
    updated_preferences = [pref for pref in preferences if pref.get("key") != normalized_key]

    if len(updated_preferences) == initial_count:
        return f"Nenhuma preferência encontrada com a chave '{key}' para remoção."

    user_persona["preferences"] = updated_preferences
    session_state['user_persona'] = user_persona
    run_context.session_state = session_state
    return f"Preferência '{normalized_key.title()}' removida com sucesso."