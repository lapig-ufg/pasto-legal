import os

from agno.models.google import Gemini
from agno.models.ollama import Ollama

MODEL_PROVIDER = os.environ.get('MODEL_PROVIDER', 'google')

if MODEL_PROVIDER == 'google':
    model = Gemini(id="gemini-3-flash-preview", temperature=0)
elif MODEL_PROVIDER == 'ollama':
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", None)
    OLLAMA_MODEL_ID = os.environ.get("OLLAMA_MODEL_ID", "gemma4:e4b-it-q8_0")
    model = Ollama(id=OLLAMA_MODEL_ID, host=OLLAMA_HOST)