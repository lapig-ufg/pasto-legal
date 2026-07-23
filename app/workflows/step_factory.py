from typing import Optional, Dict, Any

from agno.agent import Agent, RunOutput
from agno.utils.log import log_error, log_debug
from agno.workflow import StepInput, StepOutput, Step

from app.utils.interfaces.input_manager import InputManager


def _input_pre_processing(
    step_input: StepInput,
    session_state: Dict[str, Any],
    summary: bool,
    num_runs: Optional[int] = None,
) -> str:
    """Build the enriched input string for an agent step.

    Prepends the conversation summary (if available and requested) and a
    configurable number of history runs, then appends the current user input.

    Args:
        step_input: The step input containing the user message and history.
        session_state: The current session state dict.
        summary: Whether to include the running summary in the input.
        num_runs: Override for how many history runs to include.
            If None, uses ``runs_count`` from InputManager.

    Returns:
        The assembled input string for the agent.
    """
    input_manager = InputManager.model_validate(
        session_state.get("summary_state", {})
    )

    parts: list[str] = []

    if summary and input_manager.summary:
        parts.append(f"[Resumo do Histórico]\n{input_manager.summary}\n")

    effective_runs = num_runs if num_runs is not None else input_manager.runs_count
    history_msgs = step_input.get_workflow_history(num_runs=effective_runs)

    if history_msgs:
        history_block = "[Histórico de Interações]"
        for idx, msg in enumerate(history_msgs):
            user_msg, assistant_msg = msg
            history_block += (
                f"\n[Iteração {idx}]\n"
                f"Usuário: {user_msg}\n"
                f"Assistente: {assistant_msg}\n"
            )
        parts.append(history_block)

    user_input = step_input.get_input_as_string() or ""
    if user_input:
        parts.append(f"[Input do Usuário]\n{user_input}")

    return "\n".join(parts)


def _agent_executor_factory(
    agent: Agent,
    summary: bool = True,
    num_runs: Optional[int] = None,
):
    """Create a step executor that pre-processes input before running an agent.

    The executor assembles the input string via ``_input_pre_processing``
    (which prepends summary and history context), then runs the agent with
    the full session state so that agents with dynamic instructions can
    access up-to-date context.

    Args:
        agent: The Agent instance to run.
        summary: Whether to include the running summary in the input.
        num_runs: Override for how many history runs to include.

    Returns:
        A callable matching the ``StepExecutor`` signature
        ``(step_input, session_state) -> StepOutput``.
    """
    def _agent_executor(
        step_input: StepInput,
        session_state: Dict[str, Any],
    ) -> StepOutput:
        final_input = _input_pre_processing(
            step_input, session_state, summary, num_runs
        )

        try:
            user_id = step_input.workflow_session.user_id

            response: RunOutput = agent.run(
                final_input,
                user_id=user_id,
                session_state=session_state,
            )
        except Exception as exc:
            log_error(f"{agent.name} failed: {exc}")
            return StepOutput(
                content="Desculpa, houve um erro durante a execução. Tente novamente mais tarde!"
            )

        if response.status == "ERROR":
            log_error(f"{agent.name} failed.")
            return StepOutput(
                content="Desculpa, houve um erro durante a execução. Tente novamente mais tarde!"
            )

        content = response.content if response.content else ""

        return StepOutput(
            content=content,
            images=response.images if response.images else None,
            videos=response.videos if response.videos else None,
            audio=response.audio if response.audio else None,
            files=response.files if response.files else None,
            metrics=response.metrics if response.metrics else None,
        )

    return _agent_executor