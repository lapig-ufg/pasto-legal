"""Feedback evaluation and response merging for the Pasto Legal workflow.

Runs the satisfaction evaluation agent, branches based on the result
(positive / negative / neutral), persists feedback to the database, and
merges the agent response with a remediation message when the user is
frustrated.

External interface:
    feedback_workflow   -- the Workflow instance imported by main_workflow.
    merge_output_step   -- the Condition step imported by main_workflow.
"""

# --- Imports ---

from typing import Any, Dict, Optional

from agno.utils.log import log_debug, log_error
from agno.workflow import Condition, Parallel, Router, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

from app.agents.feedback_agent import remediation_agent, satisfaction_evaluation_agent
from app.agents.persona_agent import persona_manager_agent
from app.utils.interfaces.user_mood import UserMood
from app.utils.interfaces.user_persona import PersonaUpdate, CommunicationPreference, UserPersona


# --- Constants ---

# Step name used by _forward_response to look up the Intent Router output.
# This must match the Router name defined in main_workflow.py.
INTENT_ROUTER_STEP_NAME = "Intent Router"

# Default fallback satisfaction level when the evaluation agent fails.
_DEFAULT_SATISFACTION = {"level": 3, "level_message": "Neutral (default)"}


# --- Step Executors ---


def persist_positive_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> StepOutput:
    """Persist a frustrated interaction to the NegativeFeedback table."""
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #NegativeFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = NegativeFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        original_question="Original Question", # TODO: Deveria ser a mensagem que gerou a frustração (a mensagem anterior à run atual)
    #        reason_frustration=user_msg, 
    #        desired_answer=_mask_pii(normal_response),
    #        context=_mask_pii(handler_msg),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("negative feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar negative feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Negative Feedback Saved")


def persist_negative_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> StepOutput:
    """Persist an positive interaction to the PositiveFeedback table for future fine-tuning."""
    #grade = session_state.get("satisfaction_grade", 3)
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #PositiveFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = PositiveFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        user_message=_mask_pii(user_msg),
    #        assistant_response=_mask_pii(normal_response),
    #        handler_message=_mask_pii(handler_msg),
    #        grade=grade,
    #        context=_mask_pii(normal_response),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("Positive feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar positive feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Positive Feedback Saved")


def evaluate_satisfaction(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Run the satisfaction evaluation agent on the user's message and
    store the result in session_state['user_mood'].

    On the first evaluation, stores the result under 'satisfaction'.
    On subsequent evaluations (after remediation), stores under 'remediation'.

    Returns a StepOutput describing the satisfaction level, or a fallback
    StepOutput if the agent fails.
    """
    user_msg = step_input.get_input_as_string() or ""
    history_data = step_input.get_workflow_history(num_runs=1)
    user_mood = session_state.get("user_mood", None)

    effectiveness: Optional[Dict[str, Any]] = None

    try:
        evaluator_msg = ""
        if history_data:
            last_user_msg, last_workflow_response = history_data[0]
            evaluator_msg += "### Last Interaction ###\n"
            evaluator_msg += f"Last user message: {last_user_msg}\n\n"
            evaluator_msg += f"Last workflow response: {last_workflow_response}\n\n"
        evaluator_msg += f"Current user message: {user_msg}\n"

        response = satisfaction_evaluation_agent.run(
            evaluator_msg, session_state={"user_mood": user_mood}
        )
        if response and response.content:
            effectiveness = response.content.model_dump()
    except Exception as e:
        log_error(f"evaluate_satisfaction: agent failed: {e}")

    if effectiveness is None:
        log_debug("evaluate_satisfaction: no effectiveness result, using default")
        effectiveness = _DEFAULT_SATISFACTION.copy()

    if user_mood is None:
        session_state["user_mood"] = {}
        session_state["user_mood"]["satisfaction"] = effectiveness
    else:
        session_state["user_mood"]["remediation"] = effectiveness

    level = effectiveness.get("level", 3)
    level_message = effectiveness.get("level_message", "unknown")
    return StepOutput(
        content=f"The user satisfaction was evaluated as {level} ({level_message})."
    )


def satisfaction_branch_selector(step_input: StepInput, session_state: Dict[str, Any]) -> list:
    """Router selector that determines which feedback branch to follow
    based on the user's satisfaction level.

    Returns:
        ["Persist Positive Feedback"] for satisfaction level 5,
        ["Persist Negative Feedback"] for satisfaction level 1 with
            ineffective remediation,
        ["Neutral"] otherwise.
    """
    user_mood = session_state.get("user_mood", {})
    if not user_mood:
        return ["Neutral"]

    satisfaction = user_mood.get("satisfaction", {})
    satisfaction_level = satisfaction.get("level", 3)

    if satisfaction_level == 5:
        return ["Persist Positive Feedback"]
    elif satisfaction_level == 1:
        remediation = user_mood.get("remediation", {})
        effectiveness = (
            remediation.get("effectiveness", {})
            if isinstance(remediation, dict)
            else {}
        )
        if not effectiveness or effectiveness.get("level", 2) <= 2:
            return ["Persist Negative Feedback"]

    return ["Neutral"]


def manage_persona(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Conditionally run the persona manager agent and apply persona updates.

    Calls the persona manager agent only when:
    - satisfaction level >= 2, OR
    - satisfaction level < 2 AND remediation effectiveness > 3

    The agent returns a PersonaUpdate with preferences (and optionally name,
    role, regionality) to change. The executor applies those changes directly
    to session_state['user_persona'].

    After applying updates (or skipping), clears user_mood from session_state.
    """
    raw_user_mood = session_state.get("user_mood", None)
    if raw_user_mood is None:
        return
    
    user_mood = UserMood.model_validate(raw_user_mood)

    if (
        user_mood.satisfaction.level < 3 and
        user_mood.remediation and
        user_mood.remediation.effectiveness
        and user_mood.remediation.effectiveness.level < 4
        ):
        return

    user_msg = step_input.get_input_as_string() or ""
    try:
        response = persona_manager_agent.run(
            user_msg,
            session_state={"user_mood": user_mood},
        )
        if response and response.content:
            # Parse the PersonaUpdate from the agent's response
            persona_update = response.content
            if isinstance(persona_update, dict):
                persona_update = PersonaUpdate.model_validate(persona_update)

            # Apply updates to session_state["user_persona"]
            current_persona = session_state.get("user_persona", {})
            user_persona = (
                UserPersona.model_validate(current_persona) if current_persona else UserPersona()
            )

            # Apply scalar field updates (only if non-None)
            if persona_update.name is not None:
                user_persona.name = persona_update.name
            if persona_update.role is not None:
                user_persona.role = persona_update.role
            if persona_update.regionality is not None:
                user_persona.regionality = persona_update.regionality

            # Apply preference updates (add new, update existing)
            existing_prefs = {p.key: i for i, p in enumerate(user_persona.communication_preferences)}
            for new_pref in persona_update.communication_preferences:
                normalized_key = new_pref.key.strip().lower()
                if normalized_key in existing_prefs:
                    idx = existing_prefs[normalized_key]
                    user_persona.communication_preferences[idx] = CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    )
                else:
                    user_persona.communication_preferences.append(CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    ))
                    existing_prefs[normalized_key] = len(user_persona.communication_preferences) - 1

            session_state["user_persona"] = user_persona.model_dump()

        session_state["user_mood"] = None

    except Exception as e:
        log_error(f"manage_persona: agent failed: {e}")


# --- Workflow Definition ---

feedback_workflow = Workflow(
    name="Feedback Workflow",
    steps=[
        Step(
            name="Evaluate Satisfaction",
            executor=evaluate_satisfaction,
        ),
        Parallel(
            Router(
                name="Satisfaction Branch Router",
                selector=satisfaction_branch_selector,
                choices=[
                    Step(
                        name="Persist Positive Feedback",
                        executor=persist_positive_feedback,
                    ),
                    Step(
                        name="Persist Negative Feedback",
                        executor=persist_negative_feedback,
                    ),
                    Step(
                        name="Neutral",
                        executor=lambda step_input: None,
                    ),
                ],
            ),
            Step(
                name="Persona Management",
                executor=manage_persona,
            ),
            name="Feedback and Persona Parallel",
        ),
    ],
)


# --- Merge Condition ---


def _should_apply_remediation(session_state: Dict[str, Any]) -> bool:
    """Verifica de forma segura se a remediação do humor deve ser aplicada."""
    user_mood_raw = session_state.get("user_mood")
    if not user_mood_raw:
        return False

    try:
        user_mood = UserMood.model_validate(user_mood_raw)
        return bool(user_mood.remediation and user_mood.remediation.effectiveness)
    except Exception as exc:
        log_error(f"_should_apply_remediation: failed to validate user_mood - {exc}")
        return False


def _merge_output_executor(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    router_output = step_input.get_step_output(step_name=INTENT_ROUTER_STEP_NAME)

    if not router_output:
        log_error("_merge_output_executor: Intent Router step not found, skipping...")
        return StepOutput(content="Desculpa, houve um erro durante a execução. Tente novamente mais tarde!")

    audio_item = router_output.audio[0] if (router_output.audio and len(router_output.audio) > 0) else None
    is_audio = bool(audio_item and audio_item.transcript)
    
    current_content = audio_item.transcript if is_audio else router_output.content

    if _should_apply_remediation(session_state):
        try:
            response = remediation_agent.run(current_content)
            
            if is_audio:
                audio_item.transcript = response.content
            else:
                router_output.content = response.content

        except Exception as exc:
            log_error(f"_merge_output_executor: remediation agent failed - {exc}")
            return StepOutput(content="")

    return router_output


remediation_check_step = Step(
    name="Remediation Check Step",
    executor=_merge_output_executor
)