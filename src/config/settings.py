from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # HuggingFace
    HF_API_KEY: str = ""
    HF_FOOD_MODEL: str = "nateraw/food"
    HF_INFERENCE_URL: str = "https://api-inference.huggingface.co/models"

    # Google Vision (optionnel)
    GOOGLE_VISION_API_KEY: str = ""

    # Ollama (LLM local)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # USDA FoodData Central
    USDA_API_KEY: str = "DEMO_KEY"
    USDA_BASE_URL: str = "https://api.nal.usda.gov/fdc/v1"

    # MariaDB (BDD existante TPRE501)
    MARIADB_HOST: str = "localhost"
    MARIADB_PORT: int = 3306
    MARIADB_USER: str = "root"
    MARIADB_PASSWORD: str = ""
    MARIADB_DB: str = "healthai_coaching"

    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "healthai_coach"

    # Backend TPRE501 (optionnel — branché plus tard)
    BACKEND_API_URL: str = ""
    BACKEND_API_KEY: str = ""

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
