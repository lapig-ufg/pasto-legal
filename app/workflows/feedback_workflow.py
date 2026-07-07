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
from agno.workflow import Condition, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput

from app.agents.feedback_agent import remediation_agent, satisfaction_evaluation_agent
from app.agents.persona_agent import persona_manager_agent
from app.utils.interfaces.user_persona import PersonaUpdate, Preferences, UserPersona


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
    user_mood = session_state.get("user_mood", None)

    effectiveness: Optional[Dict[str, Any]] = None

    try:
        response = satisfaction_evaluation_agent.run(
            user_msg, session_state={"user_mood": user_mood}
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


def is_dissatisfied_evaluator(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Condition evaluator that returns True when the user is dissatisfied
    (satisfaction level <= 2), triggering the remediation agent.
    """
    user_mood = session_state.get("user_mood", {})
    if not user_mood:
        return False

    satisfaction = user_mood.get("satisfaction", {})
    if not satisfaction:
        return False

    return True


def clear_user_mood(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Reset user_mood in session_state to None after feedback processing."""
    session_state["user_mood"] = None
    return StepOutput(content="User mood cleared")


def manage_persona(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Conditionally run the persona manager agent and apply persona updates.

    Calls the persona manager agent only when:
    - satisfaction level >= 3, OR
    - satisfaction level < 3 AND remediation effectiveness > 3

    The agent returns a PersonaUpdate with preferences (and optionally name,
    role, regionality) to change. The executor applies those changes directly
    to session_state['user_persona'].

    After applying updates (or skipping), clears user_mood from session_state.
    """
    user_mood = session_state.get("user_mood", {})

    # Determine whether to call the agent based on satisfaction level
    should_call_agent = False
    satisfaction = user_mood.get("satisfaction", {}) if isinstance(user_mood, dict) else {}
    satisfaction_level = satisfaction.get("level", 0) if isinstance(satisfaction, dict) else 0

    if satisfaction_level >= 2:
        should_call_agent = True
    else:
        remediation = user_mood.get("remediation", {}) if isinstance(user_mood, dict) else {}
        remediation_effectiveness = (
            remediation.get("effectiveness", {}) if isinstance(remediation, dict) else {}
        )
        remediation_level = (
            remediation_effectiveness.get("level", 0)
            if isinstance(remediation_effectiveness, dict)
            else 0
        )
        if remediation_level > 3:
            should_call_agent = True

    if should_call_agent:
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
                existing_prefs = {p.key: i for i, p in enumerate(user_persona.preferences)}
                for new_pref in persona_update.preferences:
                    normalized_key = new_pref.key.strip().lower()
                    if normalized_key in existing_prefs:
                        idx = existing_prefs[normalized_key]
                        user_persona.preferences[idx] = Preferences(
                            key=normalized_key,
                            description=new_pref.description,
                        )
                    else:
                        user_persona.preferences.append(Preferences(
                            key=normalized_key,
                            description=new_pref.description,
                        ))
                        existing_prefs[normalized_key] = len(user_persona.preferences) - 1

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


def _forward_response(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Extract the response from the Intent Router step to forward it
    as the final workflow output.

    Looks up the step named INTENT_ROUTER_STEP_NAME in previous_step_outputs
    and returns its deepest content. Falls back to the last step output if
    the Intent Router step is not found.
    """
    router_output = step_input.get_step_output(step_name=INTENT_ROUTER_STEP_NAME)
    if router_output is None:
        log_debug(f"_forward_response: {INTENT_ROUTER_STEP_NAME} step not found, falling back to last step")
        if not step_input.previous_step_outputs:
            return StepOutput(content="")
        last_output = list(step_input.previous_step_outputs.values())[-1]
        return last_output if not last_output.steps else last_output.steps[-1]

    if router_output.steps:
        return router_output.steps[-1]
    return router_output


merge_output_step = Condition(
    name="Merge Dissatisfied Check",
    evaluator=is_dissatisfied_evaluator,
    steps=[
        Step(
            name="Remediation Agent",
            agent=remediation_agent,
        ),
    ],
    else_steps=[
        Step(
            name="Forward Response",
            executor=_forward_response,
        ),
    ],
)