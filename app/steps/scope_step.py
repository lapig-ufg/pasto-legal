"""Scope guardrail step: barra conteúdo fora do escopo do Pasto Legal (#123).

Reusa o texto consolidado montado pelo input_step. Se o conteúdo estiver
claramente fora do tema (pastagem/agro), bloqueia com uma mensagem amigável
(em áudio se o usuário mandou áudio). Caso contrário, passa o texto adiante.
"""
from agno.utils.log import log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.guardrails.context_gate import ContextValidator, mensagem_fora_escopo
from app.services.audio.tts import generate_speech


def _scope_executor(step_input: StepInput) -> StepOutput:
    """Barra conteúdo fora do escopo do Pasto Legal."""
    text = step_input.previous_step_content or step_input.get_input_as_string() or ""

    contexto = ContextValidator(text)
    if contexto.dentro_do_escopo:
        return StepOutput(content=text)

    aviso = mensagem_fora_escopo(contexto.assunto)

    if step_input.audio:
        try:
            user_id = step_input.workflow_session.user_id if step_input.workflow_session else "default"
            audio = generate_speech(aviso, user_id=user_id)
            if audio:
                return StepOutput(content=aviso, audio=[audio], stop=True, success=False)
        except Exception as e:
            log_error(f"scope TTS failed: {e}")

    return StepOutput(content=aviso, stop=True, success=False)


scope_step = Step(
    name="Scope Guardrail",
    executor=_scope_executor,
)