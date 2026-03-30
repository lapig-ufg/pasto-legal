from typing import Callable, Dict, Any

from agno.run import RunContext


def validate_car_hook(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que há uma propriedade armazenada no sistema.
    """
    session_state = run_context.session_state

    if session_state and 'car_selected' in session_state:
        return function_call(**arguments)

    return (
        "Não foi possível completar a análise, pois a propriedade rural ainda não foi identificada.\n"
        "Peça desculpas ao usuário e solicite que o usuário envie a localização da propriedade rural."
        "Informe que, após a identificação da propriedade, será possível prosseguir com esta análise."
    )