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