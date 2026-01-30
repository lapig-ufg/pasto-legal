
import os
import uuid
import base64
from pathlib import Path
from agno.tools import Toolkit
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class AudioGenerator(Toolkit):
    def __init__(self):
        super().__init__(name="audio_generator")
        self.register(self.generate_speech)

    def generate_speech(self, text: str, user_id: str = "default") -> str:
        """
        Generates audio speech from the given text using Google's Gemini model.
        
        Args:
            text (str): The text to be converted into speech.
            user_id (str): The user ID (e.g., phone number) to organize audio files. Defaults to "default".
            
        Returns:
            str: The message indicating where the audio file was saved.
        """
        try:
            client = genai.Client()
            
            response = client.models.generate_content(
                model='gemini-2.5-flash-preview-tts',
                contents="[Diga de forma simples e direta, use o sotaque e girias paraense]: " + text,
                config=types.GenerateContentConfig(
                    response_modalities=['AUDIO'],
                    speech_config=types.SpeechConfig(
                        language_code="pt-br",
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=os.getenv("GEMINI_VOICE_NAME", "Zephyr"),
                            )
                        )
                    ),
                )
            )
            
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                         # Calculates project root
                         script_dir = Path(__file__).parent.absolute()
                         project_root = script_dir.parent.parent.parent
                         
                         # Save to public/uploads/audio for web accessibility
                         # Was: project_root / "storage" / "audio" / user_id
                         storage_dir = project_root / "public" / "uploads" / "audio" / user_id
                         storage_dir.mkdir(parents=True, exist_ok=True)
                         
                         filename = f"speech_{uuid.uuid4()}.wav"
                         file_path = storage_dir / filename
                         
                         raw_data = part.inline_data.data
                         mime_type = part.inline_data.mime_type
                         
                         if isinstance(raw_data, bytes):
                             audio_bytes = raw_data
                         else:
                             # If it's a string, it might be base64
                             audio_bytes = base64.b64decode(raw_data)
                         
                         # Determine extension from mime_type
                         ext = ".wav"
                         is_pcm = False
                         if "mp3" in mime_type:
                             ext = ".mp3"
                         elif "ogg" in mime_type:
                             ext = ".ogg"
                         elif "L16" in mime_type or "pcm" in mime_type:
                             is_pcm = True
                             ext = ".wav"
                             
                         filename = f"speech_{uuid.uuid4()}{ext}"
                         file_path = storage_dir / filename
                         
                         if is_pcm:
                             import wave
                             # Extract rate if present, default 24000
                             framerate = 24000
                             try:
                                 if "rate=" in mime_type:
                                     framerate = int(mime_type.split("rate=")[1].split(";")[0])
                             except:
                                 pass
                                 
                             # Write WAV first
                             with wave.open(str(file_path), "wb") as wav_file:
                                 wav_file.setnchannels(1) # Mono
                                 wav_file.setsampwidth(2) # 16-bit
                                 wav_file.setframerate(framerate)
                                 wav_file.writeframes(audio_bytes)
                                 

                             # Convert to OGG using pydub
                             # Check for FFMPEG_PATH env var or use system path
                             ffmpeg_env_path = os.getenv("FFMPEG_PATH")
                             if ffmpeg_env_path:
                                 # If explicit path provided, ensure it's in PATH for pydub to find it
                                 os.environ["PATH"] += os.pathsep + ffmpeg_env_path

                             # On Windows local dev, we might need to inject the specific path if not in env
                             # This is a fallback for the specific user environment if they haven't set the env var yet
                             # But for production code, we should verify cleanliness.
                             # Let's keep the hardcoded path as a "local dev fallback" BUT strictly checked against OS.
                             if os.name == 'nt' and not ffmpeg_env_path:
                                default_win_path = r"C:\Users\Solved-Blerys-Win\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
                                if os.path.exists(default_win_path):
                                    os.environ["PATH"] += os.pathsep + default_win_path
                             
                             try:
                                 from pydub import AudioSegment
                                 # Load WAV
                                 audio = AudioSegment.from_wav(str(file_path))
                                 
                                 # Set export path (replace .wav with .ogg)
                                 ogg_path = file_path.with_suffix(".ogg")
                                 
                                 # Export as OGG (libopus is good for WhatsApp)
                                 audio.export(str(ogg_path), format="ogg", codec="libopus")
                                 
                                 # Remove original WAV to save space
                                 os.remove(file_path)
                                 
                                 # Update file_path to new OGG path
                                 file_path = ogg_path
                                 
                             except ImportError:
                                 print("pydub not installed. Returning WAV.")
                             except Exception as e:
                                 print(f"Audio conversion failed: {e}. Returning WAV.")
                         else:
                             with open(file_path, "wb") as f:
                                 f.write(audio_bytes)
                             
                         return f"Audio generated successfully at: {file_path}"
                         
            return "Failed to generate audio content."
            
        except Exception as e:
            return f"Error generating speech: {str(e)}"