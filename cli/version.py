"""
CLI wrapper for version/update notes.
Called by pi's bash tool via the bridge extension.

Usage:
  python cli/version.py '<base64-json-args>'
"""
import sys
import json
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def update_notes(args: dict) -> dict:
    base_path = Path(__file__).resolve().parent.parent
    folder_path = base_path / "docs" / "release_notes"
    if not folder_path.exists():
        return {"error": "Diretório de notas de versão não encontrado."}
    files = sorted(folder_path.glob("*.md"))
    if not files:
        return {"notes": "Nenhuma nota de versão encontrada."}
    target = files[-1]
    content = target.read_text(encoding="utf-8")
    return {"notes": content}


ACTIONS = {"update_notes": update_notes}

if __name__ == "__main__":
    args = json.loads(base64.b64decode(sys.argv[1]))
    action = args.pop("action")
    fn = ACTIONS.get(action)
    if not fn:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)
    try:
        result = fn(args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
