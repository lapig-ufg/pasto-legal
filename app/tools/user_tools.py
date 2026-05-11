from agno.tools import tool
from agno.run import RunContext

@tool
def set_user_persona(run_context: RunContext, nome: str, cidade: str, persona: str) -> str:
    """
    OBRIGATÓRIO: Registra o perfil oficial do usuário no sistema.
    Você DEVE acionar esta ferramenta assim que descobrir o nome, a cidade e a profissão/persona do usuário.

    Args:
        nome (str): O nome do usuário.
        cidade (str): A cidade do usuário.
        persona (str): OBRIGATORIAMENTE deve ser "Produtor" ou "Técnico". Interprete erros de digitação (ex: "tecnico", "agronomo", "fazendeiro") e corrija automaticamente para a string exata "Técnico" ou "Produtor".
    """
    session_state = run_context.session_state or {}
    
    persona_corrigida = persona.capitalize()

    # TODO: Salvar na tabela UserProfiles do banco de dados

    session_state['user_profile'] = {
        'nome': nome,
        'cidade': cidade,
        'persona': persona_corrigida
    }
    session_state['user_persona'] = persona_corrigida
    
    run_context.session_state = session_state
    
    return f"Perfil salvo com sucesso: {nome} de {cidade} ({persona_corrigida}). Agora adapte seu tom de voz."
