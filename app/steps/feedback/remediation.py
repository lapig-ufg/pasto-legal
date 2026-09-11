"""Remediation merge step: merges the routed response with a remediation message.

When the user is frustrated and a remediation effectiveness was recorded, runs
the remediation agent to rewrite the routed response into a softer message
(text or audio transcript). Otherwise passes the routed response through
unchanged.

External interface:
    remediation_check_step  -- Step consumed by main_workflow.
"""

from typing import Any, Dict

from agno.utils.log import log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.agents.feedback_agent import remediation_agent
from app.schemas.user_mood import UserMood


# Step name used by _merge_output_executor to look up the Intent Router output.
# This must match the Router name defined in main_workflow.py.
INTENT_ROUTER_STEP_NAME = "Intent Router"


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
    executor=_merge_output_executor,
)