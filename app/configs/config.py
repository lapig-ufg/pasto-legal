import os
from pathlib import Path
from dotenv import load_dotenv

from agno.models.google import Gemini
from agno.models.ollama import Ollama

# Define o caminho base do projeto (onde o .env geralmente fica)
BASE_DIR = Path(__file__).resolve().parent

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv(dotenv_path=BASE_DIR / ".env")

class BaseConfig:
    """Configurações comuns para todos os ambientes."""
    APP_ENV: str = os.getenv("APP_ENV", None)
    
    ARGO_APP_NAME: str = os.getenv("ARGO_APP_NAME", "Pasto Legal")

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

    MODEL_PROVIDER: str = os.getenv("MODEL_PROVIDER", "google")
    MODEL_ID: str = os.getenv("MODEL_ID", "gemini-3.1-flash-lite")

    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", None)

    OLLAMA_HOST: str = os.getenv("OLLAMA_MODEL_ID", None)
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", None)

    def __init__(self):
        if self.GEE_PROJECT is None:
            raise ValueError("GEE_PROJECT environment variables must be set.")
        if self.GEE_SERVICE_ACCOUNT is None:
            raise ValueError("GEE_SERVICE_ACCOUNT environment variables must be set.")
        if self.GEE_KEY_FILE is None:
            raise ValueError("GEE_KEY_FILE environment variables must be set.")
        
        if self.MODEL_PROVIDER == "ollama":
            if self.OLLAMA_API_KEY is None:
                raise ValueError("OLLAMA_API_KEY environment variables must be set.")

    @property
    def model(self) -> Gemini | Ollama:
        match self.MODEL_PROVIDER:
            case "google":
                if self.GOOGLE_API_KEY is None:
                    raise ValueError("GOOGLE_API_KEY environment variables must be set.")

                return Gemini(id=self.MODEL_ID, temperature=0, api_key=self.GOOGLE_API_KEY)
            case "ollama":
                return Ollama(id=self.MODEL_ID, host=self.OLLAMA_HOST, api_key=self.OLLAMA_API_KEY)
            case _:
                raise ValueError(f"Invalid model provider: {self.MODEL_PROVIDER}")


class DevelopmentConfig(BaseConfig):
    """Configurações específicas para Desenvolvimento."""
    DEBUG_MODE: bool = True

class ProductionConfig(BaseConfig):
    """Configurações específicas para Produção."""
    DEBUG_MODE: bool = False
    
    def __init__(self):
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
        

class StaggingConfig(ProductionConfig):
    """Configurações específicas para Stagging."""
    DEBUG_MODE: bool = True


# Dicionário de mapeamento dos ambientes
config_map = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "stagging": StaggingConfig
}

if (env_app := os.getenv("APP_ENV", None).lower()) is None:
    raise("APP_ENV environment variables must be set.")

if env_app not in ["production", "development", "stagging"]:
    raise("APP_ENV has to be 'production', 'development' or 'stagging'.")

# Instancia a classe de configuração correta
config = config_map[env_app]()