import textwrap

from typing import Callable, Dict, Any

from agno.agent import Agent
from agno.run import RunContext
from agno.run.team import RunInput

from app.utils.dummy_logger import log


def teste_hook(agent: Agent, run_input: RunInput) -> Any:
    """
    Hook para testar os parâmetros do hook de agente.
    """
    

    return False