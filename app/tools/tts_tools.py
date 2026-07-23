import io
import wave

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Audio

@tool(stop_after_tool_call=True)
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
    return ToolResult(content="", audios=[Audio(content=b"", transcript=text)])