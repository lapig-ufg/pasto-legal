import json
from typing import Callable, Dict, Any
from agno.run import RunContext
from datetime import datetime, timedelta

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

def validate_rate_limit_hook(run_context: Any, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """ Hook universal para evitar reprocessamento e controlar expiração (7 dias). """
    session_state = run_context.session_state or {}

    delivered_media = session_state.get("delivered_media", {})
    
    search_key = json.dumps({"func": function_call.__name__, "args": arguments}, sort_keys=True)

    if search_key in delivered_media:
        saved_date_str = delivered_media[search_key]
        try:
            saved_date = datetime.fromisoformat(saved_date_str)

            if datetime.now() - saved_date < timedelta(days=7):
                return "A mídia solicitada já foi gerada com esses exatos parâmetros e entregue nesta sessão."
        except Exception:
            pass


    try:
        result = function_call(**arguments)        
        if hasattr(result, 'content') and "Erro" in str(result.content):
            return result
        
        if not hasattr(result, 'images') or not result.images:
             return "Erro: A integração com o satélite retornou uma mídia vazia. Tente novamente."

        delivered_media[search_key] = datetime.now().isoformat()
        run_context.session_state["delivered_media"] = delivered_media

        return result

    except Exception as e:
        return f"Erro na integração externa: Falha ao executar {function_call.__name__}. Detalhe: {str(e)}"