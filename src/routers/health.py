from fastapi import APIRouter
from datetime import datetime
import httpx

from src.core.mariadb import is_available as mariadb_available
from src.core.database import get_db
from src.config.settings import settings

router = APIRouter()


@router.get("/health", summary="Health check")
async def health_check():
    services = {}

    # MariaDB
    services["mariadb"] = "connected" if mariadb_available() else "unavailable"

    # MongoDB
    try:
        db = get_db()
        await db.command("ping")
        services["mongodb"] = "connected"
    except Exception:
        services["mongodb"] = "unavailable"

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            services["ollama"] = "available"
            services["ollama_model"] = settings.OLLAMA_MODEL
            services["ollama_models_loaded"] = models
    except Exception:
        services["ollama"] = "unavailable"

    overall = "ok" if services["mariadb"] == "connected" else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-service",
        "services": services,
    }
