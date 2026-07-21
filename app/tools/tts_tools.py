import io
import wave

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Audio

@tool
def generate_speech(text: str) -> ToolResult:
    """
    Generates audio speech from the given text. It must be called last.
    
    Args:
        text (str): The full text of the content.
        
    Returns:
        ToolResult: The result containing the message and the audio media.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)

    return ToolResult(content="", audios=[Audio(content=buffer.getvalue(), transcript=text)])