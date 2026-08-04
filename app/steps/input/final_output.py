"""Final output step: extracts the deepest content from the last step output.

Drills through nested steps (Parallel, Condition, Router) until reaching a
leaf StepOutput with no sub-steps. When the leaf carries audio, transcribes
it and regenerates speech so the user receives a synthesized voice reply.

External interface:
    _final_output  -- StepExecutor consumed by main_workflow.
"""

from agno.utils.log import log_debug
from agno.workflow.types import StepInput, StepOutput

from app.services.audio.tts import generate_speech


def _final_output(step_input: StepInput) -> StepOutput:
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