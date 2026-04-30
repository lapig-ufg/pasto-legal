import json
from typing import Callable, Dict, Any
from agno.run import RunContext

def validate_selected_property_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que há uma propriedade armazenada no sistema.
    """
    session_state = run_context.session_state

    if session_state and 'registered_properties' in session_state:
        return function_call(**arguments)

    return (
        "Não foi possível completar a análise, pois não há uma propriedade selecionada.\n"
        "Peça desculpas ao usuário. Peça que o usuário informe uma propriedade."
    )

def validate_rate_limit_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook Interceptor: Gerencia o cache e a execução das ferramentas de mídia.
    Evita reprocessamento desnecessário, economiza requisições e filtra falsos positivos.
    """

    if run_context.session_state is None:
        run_context.session_state = {}
    
    midias_entregues = run_context.session_state.get("midias_entregues", {})

    clean_args = {k: v for k, v in arguments.items() if k not in ['run_context', 'session', 'session_state']}
    key_data = {
        "function_name": function_call.__name__,
        "arguments": clean_args
    }

    search_key = json.dumps(key_data, sort_keys=True)

    if search_key in midias_entregues:
        tool_name = function_call.__name__
        return (
            f"Aviso: A mídia solicitada ({tool_name}) já foi gerada com esses exatos parâmetros e entregue nesta sessão. "
            f"Avise ao usuário que a imagem já está no histórico da conversa."
        )


    try:
        result = function_call(**arguments)        
        if hasattr(result, 'content') and "Erro" in str(result.content):
            return result
        
        if not hasattr(result, 'images') or not result.images:
             return "Erro: A integração com o satélite retornou uma mídia vazia. Tente novamente."

        midias_entregues[search_key] = True
        run_context.session_state["midias_entregues"] = midias_entregues

        return result

    except Exception as e:
        return f"Erro na integração externa: Falha ao executar {function_call.__name__}. Detalhe: {str(e)}"