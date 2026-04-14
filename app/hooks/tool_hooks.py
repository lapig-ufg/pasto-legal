from typing import Callable, Dict, Any

from agno.run import RunContext


def validate_selected_property_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que há uma propriedade armazenada no sistema.
    """
    session_state = run_context.session_state

    if session_state and 'selected_property' in session_state:
        return function_call(**arguments)

    return textwrap.dedent("""
        [SISTEMA] Bloqueio de Execução: Falta o CAR da propriedade.
        
        Motivo: A ferramenta solicitada requer o Cadastro Ambiental Rural (CAR), mas ele não está no contexto atual.
        
        Ação obrigatória para o Agente:
        1. Informe que o sistema não sabe qual é a propriedade.
        2. Solicite que o usuário envie a **localização** por meio do pino de localização do WhatsApp para que o sistema identifique o CAR automaticamente.
    """).strip()
    
def validate_rate_limit_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook universal para evitar que análises e mídias pesadas sejam reprocessadas
    devido à perda de contexto em conversas longas (amnésia do LLM).
    """
    session_state = run_context.session_state or {}
    tool_name = function_call.__name__
    
    if session_state.get("midias_entregues", {}).get(tool_name):
        return f"Aviso: Esta análise ({tool_name}) já foi enviada ao usuário nesta sessão. Responda apenas em texto usando os dados do contexto que você já possui."
    

    return function_call(**arguments)