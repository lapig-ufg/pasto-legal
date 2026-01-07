import textwrap

from typing import Callable, Dict, Any


def continue_from_request(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    """
    Hook de continuação da análise após solicitação de coleta de informação.
    """
    run_context = arguments.get('run_context', {})

    if run_context and 'requester_function_call' in run_context:
        requester_function_call = run_context['requester_function_call']

        return requester_function_call(run_context)

    return textwrap.dedent("""
        Informações armazenadas com sucesso.
        
        Ação para o agente:
        1. Caso não haja mais ações a serem executadas, peça ao agente assistente que informe
        o usuário a respeito das ferramentas disponíveis com base nas informações coletadas.
        2. Caso haja mais ações a serem executadas, prossiga com o as próximas ações.
    """).strip()