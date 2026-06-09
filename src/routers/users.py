"""
Endpoints utilisateurs — lecture depuis la MariaDB TPRE501.
Permet au frontend de récupérer le profil enrichi IA d'un utilisateur.
"""
from fastapi import APIRouter, HTTPException, Query
from src.core.dependencies import AuthDep
from src.services.backend_service import get_user_profile
from src.repositories.mariadb_repository import (
    get_nutrition_history,
    get_daily_macros_summary,
    get_sport_history,
)

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get(
    "/{utilisateur_id}/profile",
    summary="Profil complet d'un utilisateur (depuis MariaDB)",
    description="Retourne le profil enrichi : données biométriques, objectif, niveau sport, stats sommeil.",
)
async def get_profile(utilisateur_id: int, _: str = AuthDep):
    profile = await get_user_profile(utilisateur_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable ou MariaDB non disponible.",
        )
    return profile


@router.get(
    "/{utilisateur_id}/nutrition/history",
    summary="Historique alimentaire",
    description="Retourne les entrées du journal alimentaire avec les macros calculées.",
)
async def nutrition_history(
    utilisateur_id: int,
    days: int = Query(default=7, ge=1, le=90),
    _: str = AuthDep,
):
    return await get_nutrition_history(utilisateur_id, days=days)


@router.get(
    "/{utilisateur_id}/nutrition/summary",
    summary="Résumé nutritionnel moyen",
    description="Moyenne des macros sur les N derniers jours.",
)
async def nutrition_summary(
    utilisateur_id: int,
    days: int = Query(default=7, ge=1, le=90),
    _: str = AuthDep,
):
    summary = await get_daily_macros_summary(utilisateur_id, days=days)
    if not summary:
        raise HTTPException(
            status_code=404,
            detail="Aucune donnée nutritionnelle disponible pour cet utilisateur.",
        )
    return summary


@router.get(
    "/{utilisateur_id}/sport/history",
    summary="Historique des séances d'entraînement",
    description="Retourne les séances avec les exercices effectués.",
)
async def sport_history(
    utilisateur_id: int,
    days: int = Query(default=30, ge=1, le=365),
    _: str = AuthDep,
):
    return await get_sport_history(utilisateur_id, days=days)
