import os
import uuid
import base64
import wave

from pathlib import Path
from google import genai

from agno.media import Audio
from agno.utils.log import log_debug, log_error


def generate_speech(text: str, user_id: str = "default") -> Audio:
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
        log_debug("Generating speech", center=True)
        log_debug(text)
        
        prompt = f"Diga de forma simples e direta, use o sotaque muito leve e girias do contexto agro: {text}"
        
        interaction = client.interactions.create(
            model="gemini-3.1-flash-tts-preview",
            input=prompt,
            response_format={"type": "audio"},
            generation_config={
                "speech_config": [
                    {"voice": "Kore"}
                ]
            }
        )
        
        if interaction.output_audio and interaction.output_audio.data:
            # O novo formato retorna o PCM codificado em base64 diretamente aqui
            audio_bytes = base64.b64decode(interaction.output_audio.data)
            
            # Cálculo dos caminhos de diretório
            script_dir = Path(__file__).parent.parent.parent.parent
            
            storage_dir = script_dir / "tmp" / "audio" / user_id
            print(storage_dir, flush=True)
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"speech{uuid.uuid4().hex[:8]}.wav"
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

                result = Audio(filepath=str(file_path), mime_type="audio/ogg")

                return result
                
            except ImportError:
                log_error("pydub não instalado.")
                
            except Exception as e:
                log_error(f"Falha na conversão do áudio: {e}.")
                    
    except Exception as e:
        log_error(f"Falha na geração do áudio: {e}.")
    
    return None
        