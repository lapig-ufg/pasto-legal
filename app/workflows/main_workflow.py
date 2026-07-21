"""Main workflow composition for the Pasto Legal multi-agent system.

Defines the root workflow (`pasto_legal_workflow`) that orchestrates greeting
detection, agent routing, feedback evaluation, and response merging.

External interface:
    pasto_legal_workflow  -- the Workflow instance imported by app.main,
                            app.interfaces.streamlit.streamlit_webapp, and
                            app.utils.debug_panel.
"""

# --- Imports ---

from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.utils.log import log_debug, log_error
from agno.workflow import Condition, Parallel, Router, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

from app.agents import (
    analyst_agent,
    manager_agent,
    question_answer_agent,
    router_agent,
    small_talk_agent,
)
from app.database.agno_db import db
from app.utils.interfaces.input_manager import InputManager
from app.utils.interfaces.user_persona import UserPersona
from app.utils.interfaces.workflow_state import WorkflowRouteEnum, WorkflowState
from app.utils.scripts.audio_tts import generate_speech
from app.workflows.feedback_workflow import feedback_workflow, merge_output_step
from app.workflows.summarization_workflow import summarization_workflow
from app.agents.welcoming_agent import welcoming_agent
from app.database.session import SessionLocal
from app.database.models import UserTermsAcceptance


# --- Step Executors ---

def _needs_onboarding(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Determines whether the user needs to go through onboarding.
    Returns True if the terms have NOT yet been accepted.
    """
    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    if session_state.get("terms_accepted"):
        return False

    user_id = session_state.get("user_id")
    if not user_id:
        return True

    db_session = SessionLocal()
    try:
        record = db_session.query(UserTermsAcceptance).filter(
            UserTermsAcceptance.user_id == user_id,
            UserTermsAcceptance.accepted == True,
        ).first()

        if record:
            session_state["terms_accepted"] = True
            return False

        return True
    finally:
        db_session.close()


def _route_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """Selector for the Intent Router. Runs the Router Agent to classify
    the user's message and returns the matching route enum value.

    If a non-AUTO route is already set in WorkflowState, returns it directly
    (manual override). Falls back to 'default' if the agent fails or the
    session state does not contain a valid WorkflowState.
    """
    raw_state = session_state.get("workflow_state")
    if raw_state is None:
        log_debug("route_selector: no workflow_state in session, defaulting to 'default'")
        return "default"

    try:
        workflow_state = WorkflowState.model_validate(raw_state)
    except Exception as e:
        log_debug(f"route_selector: invalid workflow_state: {e}, defaulting to 'default'")
        return "default"

    if workflow_state.route != WorkflowRouteEnum.AUTO:
        return workflow_state.route.value

    try:
        user_msg = step_input.get_input_as_string() or ""
        history_data = step_input.get_workflow_history(num_runs=1)

        final_message = ""
        if history_data:
            last_user_msg, last_system_response = history_data[0]
            final_message += "### Talk History ###\n"
            final_message += f"User: {last_user_msg}\n"
            final_message += f"System: {last_system_response}\n"
        final_message += f"User: {user_msg}"

        response = router_agent.run(final_message)
        route_data = response.content

        if route_data and hasattr(route_data, "route"):
            return route_data.route

        if isinstance(route_data, dict) and "route" in route_data:
            return route_data["route"]

        if isinstance(route_data, str) and len(route_data.split(" ")) == 1:
            return route_data

    except Exception as e:
        log_debug(f"route_selector: agent failed: {e}")

    return "default"


def _final_output(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Extract the deepest content from the last step output, drilling
    through nested steps (Parallel, Condition, Router) until reaching
    a leaf StepOutput with no sub-steps.
    """
    if not step_input.previous_step_outputs:
        log_debug("_final_output: no previous_step_outputs available")
        return StepOutput(content="")

    last_output = list(step_input.previous_step_outputs.values())[-1]

    while last_output.steps:
        last_output = last_output.steps[-1]

    if last_output.audio:
        audio_transcript = "\n\n".join(audio.transcript for audio in last_output.audio)

        last_output.content = audio_transcript 
        last_output.audio = [generate_speech(
            text=audio_transcript,
            user_id=step_input.workflow_session.user_id
        )]

    return last_output


# --- Input Pre-processing ---


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

            response = agent.run(
                final_input,
                user_id=user_id,
                session_state=session_state,
            )
        except Exception as exc:
            log_error(f"{agent.name} failed: {exc}")
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


# --- Workflow Definition ---

pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    add_workflow_history_to_steps=True,
    num_history_runs=1,
    steps=[
        Condition(
            name="Onboarding Check",
            evaluator=_needs_onboarding,
            steps=[
                Step(
                    name="Welcoming Agent",
                    executor=_agent_executor_factory(welcoming_agent),
                ),
            ],
            else_steps=[
                Parallel(
                    summarization_workflow,
                    feedback_workflow,
                    Router(
                        name="Intent Router",
                        selector=_route_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda step_input: None,
                            ),
                            Step(
                                name=WorkflowRouteEnum.ANALYST.value,
                                executor=_agent_executor_factory(analyst_agent),
                            ),
                            Step(
                                name=WorkflowRouteEnum.MANAGER.value,
                                executor=_agent_executor_factory(manager_agent, summary=False, num_runs=1),
                            ),
                            Step(
                                name=WorkflowRouteEnum.QUESTION_ANSWER.value,
                                executor=_agent_executor_factory(question_answer_agent, summary=False, num_runs=1),
                            ),
                            Step(
                                name=WorkflowRouteEnum.SMALL_TALK.value,
                                executor=_agent_executor_factory(small_talk_agent, summary=False, num_runs=1),
                            ),
                        ],
                    ),
                    name="Feedback and Routing",
                ),
                merge_output_step,
            ],
        ),
        Step(
            name="Final Output",
            executor=_final_output,
        ),
    ],
)