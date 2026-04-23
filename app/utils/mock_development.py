import os
import json

from pathlib import Path
from functools import wraps


def mock_property():
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if os.getenv("APP_ENV") == "development":
                from app.utils.scripts.sicar_scripts import _map_feature_to_property_record

                print(f"⚠️  [MOCK] Ignorando execução de: {func.__name__}", flush=True)
                
                dir_path = Path("app/utils/mocks/property_mock.json").resolve()
                
                try:
                    with open(dir_path, "r", encoding="utf-8") as file:
                        features = json.load(file).get('features', [])

                        return [_map_feature_to_property_record(feature) for feature in features]
                except FileNotFoundError:
                    print(f"❌ Erro: Arquivo de mock não encontrado em {dir_path}", flush=True)
                    return None
            
            return func(*args, **kwargs)
        return wrapper
    return decorator