"""Import-time env for WhatsApp router tests.

`app.interfaces.whatsapp.router` requires VALKEY_* env vars at import time.
The values are dummy: redis.Redis connects lazily and these tests never
touch Valkey.
"""
import os

for _var in ("VALKEY_HOST", "VALKEY_PORT", "VALKEY_DB"):
    os.environ.setdefault(_var, "localhost" if _var == "VALKEY_HOST" else "0")