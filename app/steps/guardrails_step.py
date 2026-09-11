"""PII guardrail step: scans the consolidated input text for personal data.

Reuses the text assembled by the previous input-processing step. If PII is
found, blocks execution and returns a warning to the user (as audio when
the user sent audio, as text otherwise). Otherwise passes the clean text
through to the following agents.

External interface:
    _guardrail_pii_executor  -- StepExecutor consumed by main_workflow.
"""
from agno.utils.log import log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.guardrails.pii_gate import check_pii, mensagem_bloqueio
from app.services.audio.tts import generate_speech


def _guardrail_pii_executor(step_input: StepInput) -> StepOutput:
    """Guardrail de PII que reusa o texto montado pelo passo anterior."""
    text = step_input.get_input_as_string() or ""

    pii_types = check_pii(text)
    if not pii_types:
        return StepOutput(content=text)

    pii_warning = mensagem_bloqueio(pii_types)

    if step_input.audio:
        try:
            user_id = step_input.workflow_session.user_id if step_input.workflow_session else "default"
            audio = generate_speech(pii_warning, user_id=user_id)
            if audio:
                return StepOutput(content=pii_warning, audio=[audio], stop=True, success=False)
        except Exception as e:
            log_error(f"guardrail TTS failed: {e}")

    return StepOutput(content=pii_warning, stop=True, success=False)


guardrails_step = Step(
    name="Guardrail PII",
    executor=_guardrail_pii_executor,
)