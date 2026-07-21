import io
import wave

from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.media import Audio

class AudioGenerator(Toolkit):
    def __init__(self):
        super().__init__(name="audio_generator")
        

    def generate_speech(self, text: str) -> ToolResult:
        """
        Generates audio speech from the given text. It must be called last.
        
        Args:
            text (str): The text to be converted into speech. It must be a concise version of the content.
            
        Returns:
            ToolResult: The result containing the message and the audio media.
        """
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(44100)

        return ToolResult(content="", audios=[Audio(content=buffer.getvalue(), transcript=text)])

audio_gen = AudioGenerator()
audioTTS = audio_gen.generate_speech