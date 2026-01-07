import textwrap

from typing import Callable, Dict, Any


def validate_car_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que o CAR (Cadastro Ambiental Rural) esteja presente.
    """
    run_context = arguments.get('run_context', {})

    if run_context and 'car' in run_context:
        return function_call(**arguments)

    return textwrap.dedent("""
        [SISTEMA] Bloqueio de Execução: Falta o CAR da propriedade.
        
        Motivo: A ferramenta solicitada requer o Cadastro Ambiental Rural (CAR), mas ele não está no contexto atual.
        
        Ação obrigatória para o Agente:
        1. Informe ao usuário que o sistema não sabe qual é a propriedade.
        2. Solicite que o usuário envie a **localização** (pino de localização) via WhatsApp para que o sistema identifique o CAR automaticamente.
    """).strip()


def validate_car_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    pass