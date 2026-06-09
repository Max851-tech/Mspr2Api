"""Authentification par API Key pour sécuriser les endpoints."""
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from src.config.settings import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Vérifie la clé API. En dev, la clé est optionnelle."""
    if settings.APP_ENV == "development":
        return api_key or "dev"

    if not api_key or api_key != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé API invalide ou manquante",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
