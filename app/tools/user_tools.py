from agno.tools import tool
from agno.run import RunContext

@tool
def set_user_persona(run_context: RunContext, nome: str, cidade: str, persona: str) -> str:
    """
    Registra o perfil oficial do usuário no sistema. 
    A persona deve ser estritamente "Produtor" ou "Técnico".
    """
    # TODO: Salvar na tabela UserProfiles do banco de dados
    
    run_context.session_state['user_profile'] = {
        'nome': nome,
        'cidade': cidade,
        'persona': persona
    }
    
    return f"Perfil salvo com sucesso: {nome} de {cidade} ({persona})."