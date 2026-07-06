import os
import uuid
import base64
import wave
from pathlib import Path
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.media import Audio
from google import genai
from dotenv import load_dotenv

load_dotenv()

class AudioGenerator(Toolkit):
    def __init__(self):
        super().__init__(name="audio_generator", stop_after_tool_call_tools=["generate_speech"])
        

    def generate_speech(self, text: str, user_id: str = "default") -> ToolResult:
        """
        Generates audio speech from the given text using Google's Gemini model.
        
        It must be called last; this will terminate the processing and send response to user.
        
        Args:
            text (str): The text to be converted into speech.
            
        Returns:
            ToolResult: The result containing the message and the audio media.
        """
        try:
            client = genai.Client()
            print("Generating speech with Gemini 3.1...", flush=True)
            print(text, flush=True)
            
            # Recupera a voz do ambiente (Padrão alterado para 'Kore' que é suportado na v3.1)
            voice_name = os.getenv("GEMINI_VOICE_NAME", "Kore")
            
            # Estrutura o prompt definindo o 'Locutor' para casar com o speech_config
            prompt = f"Locutor: [Diga de forma simples e direta, use o sotaque e girias do contexto agro]: {text}"
            
            # Nova chamada de TTS utilizando client.interactions.create
            interaction = client.interactions.create(
                model="gemini-3.1-flash-tts-preview",
                input=prompt,
                response_format={"type": "audio"},
                generation_config={
                    "speech_config": [
                        {"speaker": "Locutor", "voice": voice_name}
                    ]
                }
            )
            
            if interaction.output_audio and interaction.output_audio.data:
                # O novo formato retorna o PCM codificado em base64 diretamente aqui
                audio_bytes = base64.b64decode(interaction.output_audio.data)
                
                # Cálculo dos caminhos de diretório
                script_dir = Path(__file__).parent.absolute()
                project_root = script_dir.parent.parent
                
                storage_dir = project_root / "tmp" / "audio" / user_id
                storage_dir.mkdir(parents=True, exist_ok=True)
                
                filename = f"speech_{uuid.uuid4()[:16]}.wav"
                file_path = storage_dir / filename
                
                # Grava o arquivo WAV temporário a partir do PCM retornado
                framerate = 24000  # Taxa padrão do Gemini TTS
                with wave.open(str(file_path), "wb") as wav_file:
                    wav_file.setnchannels(1)      # Mono
                    wav_file.setsampwidth(2)     # 16-bit
                    wav_file.setframerate(framerate)
                    wav_file.writeframes(audio_bytes)
                
                # --- Configuração do ambiente FFMPEG para conversão ---
                ffmpeg_env_path = os.getenv("FFMPEG_PATH")
                if ffmpeg_env_path:
                    os.environ["PATH"] += os.pathsep + ffmpeg_env_path

                if os.name == 'nt' and not ffmpeg_env_path:
                    default_win_path = r"C:\Users\Solved-Blerys-Win\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
                    if os.path.exists(default_win_path):
                        os.environ["PATH"] += os.pathsep + default_win_path
                
                # --- Conversão de WAV para OGG usando Pydub ---
                try:
                    from pydub import AudioSegment
                    # Carrega o arquivo WAV gerado
                    audio = AudioSegment.from_wav(str(file_path))
                    
                    # Define o novo caminho com a extensão .ogg
                    ogg_path = file_path.with_suffix(".ogg")
                    
                    # Exporta em OGG com o codec libopus (ideal para WhatsApp)
                    audio.export(str(ogg_path), format="ogg", codec="libopus")
                    
                    # Remove o WAV temporário para poupar espaço
                    os.remove(file_path)
                    
                    # Atualiza o ponteiro do arquivo final para o OGG
                    file_path = ogg_path
                    
                except ImportError:
                    print("pydub não instalado. Retornando arquivo em WAV.")
                except Exception as e:
                    print(f"Falha na conversão do áudio: {e}. Retornando arquivo em WAV.")
                
                result = ToolResult(
                    content=text,
                    audios=[Audio(filepath=str(file_path))]
                )
                print(f"DEBUG ToolResult: {result}", flush=True)
                return result
                        
            return ToolResult(content="Falha ao gerar o conteúdo de áudio.")
            
        except Exception as e:
            return ToolResult(content=f"Erro ao gerar fala: {str(e)}")

audio_gen = AudioGenerator()
audioTTS = audio_gen.generate_speech