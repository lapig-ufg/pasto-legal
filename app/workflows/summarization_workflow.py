"""Summarization workflow for the Pasto Legal multi-agent system.

Periodically condenses conversation history into a running summary
to keep the context window manageable while preserving key information.

External interface:
    summarization_workflow  -- the Step instance imported by main_workflow.
"""

import textwrap
from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.run import RunContext
from agno.utils.log import log_debug, log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.configs.config import config
from app.utils.interfaces.input_manager import InputManager

SUMMARY_THRESHOLD = 6
HISTORY_WINDOW = 4


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    summary_state = InputManager.model_validate(
        session_state.get("summary_state", {})
    )

    summary_prompt = ""
    if summary_state.summary:
        summary_prompt = textwrap.dedent(f"""\
            <resumo-anterior>
            {summary_state.summary}
            </resumo-anterior>""")

    instructions = textwrap.dedent(f"""\
        # Perfil e Objetivo
        Você é um agente especializado em resumo e condensação de contexto conversacional.
        Sua função é produzir um resumo compacto que preserve o essencial para a continuidade
        da conversa, descartando detalhes supérfluos e informações que não são mais relevantes.

        # Tarefa
        Você receberá como entrada um histórico de interações entre o usuário e o sistema.
        Analise esse histórico e produza um novo resumo que:
        - Mantenha o tópico principal da conversa e a intenção do usuário.
        - Preserve dados concretos citados pelo usuário (nomes de propriedades, números,
          preferências, localidades, etc.).
        - Remova informações que o usuário já abandonou (mudança de assunto, correções, etc.).
        - Integre, se existir, o resumo anterior como base — atualizando-o com as novas
          informações e removendo o que perdeu relevância.

        # Regras
        - O resumo final deve ter no máximo 1000 tokens.
        - Não copie trechos literais longos; reformule de forma concisa.
        - Priorize contexto e intenção, não decore diálogos.
        - Se o usuário mudou de assunto, descarte o contexto anterior que não é mais útil.
        - Mantenha referências a dados gerados pelo sistema que podem ser úteis ou
          consultados pelo usuário na conversa atual.

        # Formato de Saída
        Produza apenas o texto do resumo, sem títulos, marcadores ou explicações adicionais.

        {summary_prompt}""")

    return instructions


summary_agent = Agent(
    name="Summary Agent",
    model=config.model,
    instructions=get_instructions,
)


def summarization_executor(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> Optional[StepOutput]:
    summary_state = InputManager.model_validate(
        session_state.get("summary_state", {})
    )

    if summary_state.runs_count < SUMMARY_THRESHOLD:
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        log_debug(
            f"summarization_executor: skipping (runs_count={summary_state.runs_count})"
        )
        return None

    history_msgs = step_input.get_workflow_history(num_runs=SUMMARY_THRESHOLD)
    if not history_msgs:
        log_debug("summarization_executor: no history available, skipping")
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        return None

    recent_msgs = history_msgs[:HISTORY_WINDOW]

    summary_input = ""
    for idx, msg in enumerate(recent_msgs):
        request_msg, response_msg = msg
        summary_input += (
            f"[Iteração {idx}]\n"
            f"Usuário: {request_msg}\n"
            f"Assistente: {response_msg}\n\n"
        )

    user_msg = step_input.get_input_as_string() or ""
    if user_msg:
        summary_input += f"[Última Iteração]\nUsuário: {user_msg}\n"

    try:
        response = summary_agent.run(
            summary_input,
            session_state=session_state,
        )
    except Exception as exc:
        log_error(f"summarization_executor: agent failed: {exc}")
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        return None

    if response and response.content:
        summary_state.summary = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        summary_state.runs_count = 1
    else:
        log_debug("summarization_executor: agent returned empty content")
        summary_state.runs_count += 1

    session_state["summary_state"] = summary_state.model_dump()
    return StepOutput(content="Summary updated")


summarization_workflow = Step(
    name="Summarization Step",
    executor=summarization_executor,
)