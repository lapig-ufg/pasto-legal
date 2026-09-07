"""Agent-facing TTS tool shim.

This is a lightweight agno ``@tool`` that tags the agent response with an
``Audio`` carrying only the transcript — it does NOT synthesize audio here.
The actual speech synthesis happens once, at the end of the run, in
``app.steps.input.final_output._final_output`` (and the PII guardrail), which
call the real implementation in ``app.services.audio.tts.generate_speech``.

Keeping this as a shim lets the agent "claim" it produced audio so the
workflow knows to synthesize speech for that turn, without paying the
synthesis cost on every intermediate agent step.
"""

from agno.media import Audio
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error

from app.configs.prompts import get_tool_description


@tool(description=get_tool_description("tts_tools", "generate_speech"))
def generate_speech(text: str) -> ToolResult:
    """
    Gera áudio falado (conversão de texto em fala) a partir de um texto fornecido.

    QUANDO USAR:
    - Chame esta ferramenta APENAS quando o usuário solicitar explicitamente uma resposta em áudio ou voz.
    - Chame esta ferramenta se a sessão atual ou a preferência do sistema exigir respostas em áudio.

    Args:
        text (str): O texto completo do conteúdo.

    Returns:
        ToolResult: Objeto de resultado contendo a fala gerada.
    """
    log_debug("generate_speech: marcando turn para síntese de áudio")
    try:
        return ToolResult(content="Áudio gerado com sucesso!", audios=[Audio(content=bytes(), transcript=text)])
    except Exception as e:
        log_error(f"generate_speech: {e}")
        return ToolResult(content=f"Erro ao gerar áudio: {str(e)}")