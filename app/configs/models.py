import os

from agno.models.google import Gemini
from agno.models.ollama import Ollama

MODEL_PROVIDER = os.environ.get('MODEL_PROVIDER', 'gemini')

if MODEL_PROVIDER == 'gemini':
    model = Gemini(id="gemini-3-flash-preview", temperature=0)
elif MODEL_PROVIDER == 'ollama':
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", None)
    model = Ollama(id="gemma4:e4b-it-q8_0", host=OLLAMA_HOST)