import json

from datetime import datetime
from typing import Callable, Dict, Any

from agno.run import RunContext


def validate_selected_property_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que há uma propriedade armazenada no sistema.
    """
    session_state = run_context.session_state

    if session_state and 'selected_property' in session_state:
        return function_call(**arguments)

    return (
        "Não foi possível completar a análise, pois não há uma propriedade selecionada.\n"
        "Peça desculpas ao usuário. Peça que o usuário informe uma propriedade."
    )


def validate_rate_limit_hook(run_context: Any, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook universal para evitar que análises e mídias pesadas sejam reprocessadas
    devido à perda de contexto em conversas longas (amnésia do LLM).
    """
    session_state = run_context.session_state or {}
    
    delivered_media: Dict[str, Dict[str, Any]] = session_state.get("delivered_media", {})

    clean_args = {k: v for k, v in arguments.items() if k not in ['run_context', 'session', 'session_state']}

    today = datetime.now().date()

    key_data = {
        "function_name": function_call.__name__,
        "arguments": clean_args,
        "date": today.isoformat()
    }
    search_key = json.dumps(key_data, sort_keys=True)

    delete_list = []
    for key, value_data in delivered_media.items():
        entry_date_str = value_data.get("timestamp")
        
        if entry_date_str:
            entry_date = datetime.fromisoformat(entry_date_str).date()
            dias_passados = (today - entry_date).days
            
            if dias_passados > 6:
                delete_list.append(key)

    for key in delete_list:
        del delivered_media[key]

    if search_key in delivered_media and delivered_media[search_key].get("delivered") is True:
        tool_name = function_call.__name__
        return (
            f"Aviso: Esta análise ({tool_name}) já foi enviada ao usuário nesta sessão. "
            f"Responda apenas em texto usando os dados do contexto que você já possui."
        )

    delivered_media[search_key] = {
        "delivered": True,
        "timestamp": today.isoformat()
    }
    
    if run_context.session_state is None:
        run_context.session_state = {}
        
    run_context.session_state["delivered_media"] = delivered_media

    return function_call(**arguments)