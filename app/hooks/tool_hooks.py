import textwrap

from typing import Callable, Dict, Any

from agno.run import RunContext


def validate_car_hook(run_context: RunContext, function_name: str, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que o CAR (Cadastro Ambiental Rural) esteja presente.
    """
    session_state = run_context.session_state

    if session_state and 'car' in session_state:
        return function_call(**arguments)

    return textwrap.dedent("""
        [SISTEMA] Bloqueio de Execução: Falta o CAR da propriedade.
        
        Motivo: A ferramenta solicitada requer o Cadastro Ambiental Rural (CAR), mas ele não está no contexto atual.
        
        Ação obrigatória para o Agente:
        1. Informe que o sistema não sabe qual é a propriedade.
        2. Solicite que o usuário envie a **localização** por meio do pino de localização do WhatsApp para que o sistema identifique o CAR automaticamente.
    """).strip()