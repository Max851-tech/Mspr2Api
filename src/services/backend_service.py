"""
Service de récupération des données utilisateur depuis la MariaDB TPRE501.

Priorité :
  1. MariaDB directe (si disponible) → profil complet + historique réel
  2. Cache MongoDB (profil mis en cache < 1h)
  3. Retourne None → le profil doit être fourni dans la requête (mode standalone)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.repositories.mariadb_repository import get_user_full_profile
from src.core.database import get_db
from src.models.db_documents import UserProfileCacheDocument

logger = logging.getLogger(__name__)

COLLECTION = "user_profiles_ai"
CACHE_TTL_SECONDS = 3600  # 1 heure


async def get_user_profile(utilisateur_id: int) -> Optional[dict]:
    """
    Récupère le profil utilisateur enrichi pour l'IA.

    1. Tentative MariaDB → données fraîches + mise en cache MongoDB
    2. Fallback cache MongoDB (< 1h)
    3. None si tout échoue (mode standalone)
    """
    # 1. MariaDB directe
    profile = await get_user_full_profile(utilisateur_id)
    if profile:
        await _update_cache(str(utilisateur_id), profile)
        return profile

    # 2. Cache MongoDB
    cached = await _get_from_cache(str(utilisateur_id))
    if cached:
        logger.info(f"Profil utilisateur {utilisateur_id} servi depuis le cache MongoDB.")
        return cached

    logger.warning(
        f"Profil utilisateur {utilisateur_id} introuvable. "
        "Mode standalone : fournir le profil dans la requête."
    )
    return None


async def _get_from_cache(user_id: str) -> Optional[dict]:
    """Lit le profil depuis MongoDB si récent (< TTL)."""
    try:
        db = get_db()
        doc = await db[COLLECTION].find_one({"user_id": user_id})
        if not doc:
            return None

        age_seconds = (datetime.utcnow() - doc["updated_at"]).total_seconds()
        if age_seconds > CACHE_TTL_SECONDS:
            return None

        doc.pop("_id", None)
        return doc
    except Exception as e:
        logger.warning(f"Impossible de lire le cache MongoDB: {e}")
        return None


async def _update_cache(user_id: str, profile_data: dict):
    """Met à jour le cache MongoDB avec les données fraîches de la MariaDB."""
    try:
        db = get_db()
        doc = UserProfileCacheDocument(
            user_id=user_id,
            age=profile_data.get("age", 25),
            weight_kg=profile_data.get("weight_kg", 70.0),
            height_cm=profile_data.get("taille_cm", 170.0),
            goal=profile_data.get("goal", "general_health"),
            fitness_level=profile_data.get("fitness_level", "beginner"),
            allergies=profile_data.get("allergies", []),
            dietary_preferences=profile_data.get("dietary_preferences", []),
            budget_per_day_eur=profile_data.get("budget_per_day_eur"),
            injuries=profile_data.get("injuries", []),
            last_synced_at=datetime.utcnow(),
        )
        await db[COLLECTION].update_one(
            {"user_id": user_id},
            {"$set": doc.model_dump()},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"Impossible de mettre à jour le cache MongoDB: {e}")
