from typing import Literal

from agno.tools import tool
from agno.run import RunContext
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description
from app.database.session import SessionLocal, engine
from app.database.models import UserProfile


# =====================================================================
# HELPERS INTERNOS (não são tools — o agente não enxerga)
# =====================================================================


def _persistir_perfil(user_id: str, **campos) -> bool:
    """Grava nome e/ou papel na tabela user_profile (cria a linha se não existir).

    Recebe os campos por keyword (name=..., role=...) para que cada tool grave
    apenas o que ela conhece, sem apagar o que a outra já gravou.
    """
    UserProfile.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        record = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if record is None:
            record = UserProfile(user_id=user_id, **campos)
            db.add(record)
        else:
            for chave, valor in campos.items():
                setattr(record, chave, valor)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        log_error(f"_persistir_perfil: falha para user_id={user_id}: {e}")
        return False
    finally:
        db.close()

# =====================================================================
# TOOLS PARA ATRIBUTOS PRINCIPAIS
# =====================================================================

@tool(description=get_tool_description("persona_tools", "update_persona_name"))
def update_persona_name(name: str, run_context: RunContext) -> str:
    """
    Atualiza organicamente o nome da persona (perfil) do usuário no estado da sessão.

    Use esta ferramenta apenas quando o usuário informar ou confirmar o seu nome 
    durante a conversa de forma natural.

    Args:
        name (str): Nome próprio do usuário (ex: "João", "Maria").
    """

    log_debug(f"update_persona_name: name={name}")
    try:
        nome = name.strip()

        if not nome or len(nome) > 60 or any(c.isdigit() for c in nome):
            log_warning(f"update_persona_name: nome recusado -> {nome!r}")
            return (
                "Nome inválido. Peça ao usuário que informe apenas como prefere "
                "ser chamado, sem números."
            )

        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        user_persona['name'] = nome

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state

        user_id = run_context.user_id or session_state.get("user_id")
        if user_id:
            _persistir_perfil(user_id, name=nome)
        else:
            log_warning("update_persona_name: user_id ausente, perfil salvo apenas na sessão")

        log_debug(f"update_persona_name: nome atualizado para {nome}")
        return f"Nome atualizado com sucesso para: {nome}"
    except Exception as e:
        log_error(f"update_persona_name: {e}")
        return f"Erro ao atualizar nome da persona: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_role"))
def update_persona_role(role: Literal["Produtor", "Técnico"], run_context: RunContext) -> str:
    """
    Atualiza organicamente o papel profissional da persona do usuário no estado da sessão.

    Use esta ferramenta quando identificar claramente se o usuário é um produtor rural
    ou um assistente técnico/agrônomo.

    Args:
        role (Literal["Produtor", "Técnico"]): O papel profissional identificado.
    """
    log_debug(f"update_persona_role: role={role}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        # O Literal do agno já garante que só chega "Produtor" ou "Técnico".
        user_persona['role'] = role

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state

        user_id = run_context.user_id or session_state.get("user_id")
        if user_id:
            _persistir_perfil(user_id, role=role)
        else:
            log_warning("update_persona_role: user_id ausente, perfil salvo apenas na sessão")

        log_debug(f"update_persona_role: papel atualizado para {role}")
        return f"Papel profissional atualizado com sucesso para: {role}"
    except Exception as e:
        log_error(f"update_persona_role: {e}")
        return f"Erro ao atualizar papel da persona: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_region"))
def update_persona_region(regionality: str, run_context: RunContext) -> str:
    """
    Atualiza organicamente a regionalidade/localização da persona no estado da sessão.

    Use esta ferramenta quando o usuário mencionar a cidade, estado ou região onde atua.

    Args:
        regionality (str): Cidade, estado ou região do usuário (ex: "Sorriso - MT", "Sul de Minas").
    """
    log_debug(f"update_persona_region: regionality={regionality}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})

        user_persona['regionality'] = regionality.strip().title()

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"update_persona_region: regionalidade atualizada para {user_persona['regionality']}")
        return f"Regionalidade atualizada com sucesso para: {user_persona['regionality']}"
    except Exception as e:
        log_error(f"update_persona_region: {e}")
        return f"Erro ao atualizar regionalidade da persona: {str(e)}"


# =====================================================================
# TOOLS PARA GERENCIAMENTO DE PREFERÊNCIAS
# =====================================================================

@tool(description=get_tool_description("persona_tools", "create_persona_preference"))
def create_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Adiciona uma nova preferência, interesse, hobbie ou comportamento descoberto sobre o usuário.

    Use esta ferramenta de forma sutil sempre que captar um gosto, rotina ou preferência do usuário.
    Evite duplicar chaves existentes. Se a chave já existir, use 'update_persona_preference'.

    Args:
        key (str): Uma palavra-chave curta em minúsculas identificando a categoria (ex: "cultura", "cafe", "horario_contato", "canal_favorito").
        description (str): Detalhes sobre o gosto ou comportamento do usuário naquela categoria.
    """
    log_debug(f"create_persona_preference: key={key}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})
        
        if "preferences" not in user_persona or not isinstance(user_persona["preferences"], list):
            user_persona["preferences"] = []

        normalized_key = key.strip().lower()

        for pref in user_persona["preferences"]:
            if pref.get("key") == normalized_key:
                log_warning(f"Preferência já existe: {normalized_key}")
                return f"A preferência '{key}' já existe. Use 'update_persona_preference' para modificá-la."

        user_persona["preferences"].append({
            "key": normalized_key,
            "description": description.strip()
        })

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"create_persona_preference: preferência '{normalized_key}' registrada")
        return f"Nova preferência registrada: {normalized_key.title()} -> {description}"
    except Exception as e:
        log_error(f"create_persona_preference: {e}")
        return f"Erro ao registrar preferência: {str(e)}"


@tool(description=get_tool_description("persona_tools", "update_persona_preference"))
def update_persona_preference(key: str, description: str, run_context: RunContext) -> str:
    """
    Atualiza uma preferência ou comportamento já existente na persona do usuário.

    Use esta ferramenta quando o usuário mudar de opinião ou trouxer novas informações 
    sobre um ponto que já havia sido mapeado anteriormente.

    Args:
        key (str): A palavra-chave exata da preferência a ser atualizada (ex: "cultura", "cafe").
        description (str): A nova descrição atualizada que substituirá a anterior.
    """
    log_debug(f"update_persona_preference: key={key}")
    try:
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
            log_warning(f"Preferência não encontrada para atualizar: {normalized_key}")
            return f"Não foi possível atualizar: A preferência com a chave '{key}' não foi encontrada."

        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"update_persona_preference: preferência '{normalized_key}' atualizada")
        return f"Preferência '{normalized_key.title()}' atualizada com sucesso."
    except Exception as e:
        log_error(f"update_persona_preference: {e}")
        return f"Erro ao atualizar preferência: {str(e)}"


@tool(description=get_tool_description("persona_tools", "remove_persona_preference"))
def remove_persona_preference(key: str, run_context: RunContext) -> str:
    """
    Remove uma preferência específica do perfil do usuário caso ela não seja mais válida.

    Args:
        key (str): A palavra-chave da preferência que deve ser removida.
    """
    log_debug(f"remove_persona_preference: key={key}")
    try:
        session_state = run_context.session_state or {}
        user_persona = session_state.get("user_persona", {})
        preferences = user_persona.get("preferences", [])

        normalized_key = key.strip().lower()
        
        initial_count = len(preferences)
        updated_preferences = [pref for pref in preferences if pref.get("key") != normalized_key]

        if len(updated_preferences) == initial_count:
            log_warning(f"Preferência não encontrada para remoção: {normalized_key}")
            return f"Nenhuma preferência encontrada com a chave '{key}' para remoção."

        user_persona["preferences"] = updated_preferences
        session_state['user_persona'] = user_persona
        run_context.session_state = session_state
        log_debug(f"remove_persona_preference: preferência '{normalized_key}' removida")
        return f"Preferência '{normalized_key.title()}' removida com sucesso."
    except Exception as e:
        log_error(f"remove_persona_preference: {e}")
        return f"Erro ao remover preferência: {str(e)}"