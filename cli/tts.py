"""
CLI wrapper for TTS (text-to-speech) via Google Gemini.
Called by pi's bash tool via the pi subprocess extension.

Usage:
  python cli/tts.py '<base64-json-args>'
"""
import sys
import json
import os
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def generate(args: dict) -> dict:
    from api.services.audio.tts import generate_speech
    audio = generate_speech(args["text"], user_id=args.get("user_id", "default"))
    if audio and audio.filepath:
        return {"audio_path": audio.filepath}
    return {"error": "Falha ao gerar áudio"}


ACTIONS = {"generate": generate}

if __name__ == "__main__":
    args = json.loads(base64.b64decode(sys.argv[1]))
    action = args.pop("action", "generate")
    fn = ACTIONS.get(action)
    if not fn:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)
    try:
        result = fn(args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
