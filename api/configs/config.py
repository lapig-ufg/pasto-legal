import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path.cwd()
load_dotenv(dotenv_path=BASE_DIR / ".env")


class BaseConfig:
    """Configurações comuns para todos os ambientes."""
    APP_ENV: str = os.getenv("APP_ENV", None)

    DATABASE_TYPE: str = os.getenv("DATABASE_TYPE", None)

    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", None)
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", None)
    POSTGRES_DBNAME: str = os.getenv("POSTGRES_DBNAME", None)
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", None)
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", None)

    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", None)
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", None)
    WHATSAPP_WEBHOOK_URL: str = os.getenv("WHATSAPP_WEBHOOK_URL", None)
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", None)
    WHATSAPP_APP_SECRET: str = os.getenv("WHATSAPP_APP_SECRET", None)

    GEE_PROJECT: str = os.getenv("GEE_PROJECT", None)
    GEE_SERVICE_ACCOUNT: str = os.getenv("GEE_SERVICE_ACCOUNT", None)
    GEE_KEY_FILE: str = os.getenv("GEE_KEY_FILE", None)

    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", None)

    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", None)
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", None)
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", None)
    S3_BUCKET: str = os.getenv("S3_BUCKET", "pasto-legal")
    S3_REGION: str = os.getenv("S3_REGION", None)

    def __init__(self):
        if self.GEE_PROJECT is None:
            raise ValueError("GEE_PROJECT environment variables must be set.")
        if self.GEE_SERVICE_ACCOUNT is None:
            raise ValueError("GEE_SERVICE_ACCOUNT environment variables must be set.")
        if self.GEE_KEY_FILE is None or not os.path.exists(self.GEE_KEY_FILE):
            if os.path.exists("/app/global-pasture-watch-f46d09d13b4e.json"):
                self.GEE_KEY_FILE = "/app/global-pasture-watch-f46d09d13b4e.json"
            else:
                raise ValueError("GEE_KEY_FILE environment variables must be set.")


class DevelopmentConfig(BaseConfig):
    DEBUG_MODE: bool = True


class ProductionConfig(BaseConfig):
    DEBUG_MODE: bool = False

    def __init__(self):
        super().__init__()
        if self.POSTGRES_HOST is None:
            raise ValueError("POSTGRES_HOST environment variables must be set.")
        if self.POSTGRES_PORT is None:
            raise ValueError("POSTGRES_PORT environment variables must be set.")
        if self.POSTGRES_DBNAME is None:
            raise ValueError("POSTGRES_DBNAME environment variables must be set.")
        if self.POSTGRES_USER is None:
            raise ValueError("POSTGRES_USER environment variables must be set.")
        if self.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD environment variables must be set.")
        if self.WHATSAPP_ACCESS_TOKEN is None:
            raise ValueError("WHATSAPP_ACCESS_TOKEN environment variables must be set.")
        if self.WHATSAPP_VERIFY_TOKEN is None:
            raise ValueError("WHATSAPP_VERIFY_TOKEN environment variables must be set.")
        if self.WHATSAPP_WEBHOOK_URL is None:
            raise ValueError("WHATSAPP_WEBHOOK_URL environment variables must be set.")
        if self.WHATSAPP_PHONE_NUMBER_ID is None:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID environment variables must be set.")
        if self.WHATSAPP_APP_SECRET is None:
            raise ValueError("WHATSAPP_APP_SECRET environment variables must be set.")
        if self.S3_ENDPOINT_URL is None:
            raise ValueError("S3_ENDPOINT_URL environment variables must be set.")
        if self.S3_ACCESS_KEY is None:
            raise ValueError("S3_ACCESS_KEY environment variables must be set.")
        if self.S3_SECRET_KEY is None:
            raise ValueError("S3_SECRET_KEY environment variables must be set.")


class StaggingConfig(ProductionConfig):
    DEBUG_MODE: bool = True


config_map = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "stagging": StaggingConfig,
}

if (env_app := os.getenv("APP_ENV", None)) is None:
    raise ValueError("APP_ENV environment variables must be set.")

env_app = env_app.lower()
if env_app not in config_map:
    raise ValueError(f"APP_ENV must be one of: {', '.join(config_map)}. Got: {env_app}")

config = config_map[env_app]()

from api.configs.logging_config import setup_logging  # noqa: E402

setup_logging(config)
