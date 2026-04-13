import os
from functools import wraps

def mock_dev_only(value):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if os.getenv("ENV") == "development":
                print(f"⚠️ [MOCK] Ignorando execução pesada de: {func.__name__}")
                return value
            
            return func(*args, **kwargs)
        return wrapper
    return decorator