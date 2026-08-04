"""Input pre-processing step: converts media (audio/image) to text.

Executes the transcription agent for audio and the description agent for
images, consolidating everything into a single text for the following
steps (PII guardrail and business agents).

On transcription/description failure, logs the error and continues with
whatever text is available (resilient fallback).

External interface:
    _input_processing_executor  -- StepExecutor consumed by main_workflow.
"""
from agno.utils.log import log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.agents import audio_transcription_agent, image_description_agent


def _input_processing_executor(step_input: StepInput) -> StepOutput:
    """Converte mídia (áudio e imagem) em texto e monta o input final."""
    parts: list[str] = []

    texto = step_input.get_input_as_string() or ""
    if texto:
        parts.append(texto)

    if step_input.images:
        try:
            response = image_description_agent.run("", images=step_input.images)
            description = response.content or ""
            if description:
                parts.append(f"[IMAGEM]{description}[/IMAGEM]")
        except Exception as e:
            log_error(f"image description failed: {e}")

    if step_input.audio:
        try:
            response = audio_transcription_agent.run("", audio=step_input.audio)
            transcription = response.content or ""
            if transcription:
                parts.append(transcription)
        except Exception as e:
            log_error(f"audio transcription failed: {e}")

    return StepOutput(content="\n".join(parts))

input_step = Step(
    name="Input Step",
    executor=_input_processing_executor,
)