import uuid
import logging
from fastapi import APIRouter, Request, Header
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.dependencies import AuthDep
from src.models.db_documents import RecommendationDocument
from src.models.recommendation import (
    NutritionRecommendationRequest,
    NutritionRecommendationResponse,
    SportRecommendationRequest,
    SportRecommendationResponse,
    MealPlan,
    ExerciseSession,
)
from src.services.nutrition_service import detect_imbalances, calculate_daily_targets
from src.repositories.recommendation_repository import save_recommendation, get_recommendations_by_user
from src.services.llm_service import (
    generate_nutrition_recommendations,
    generate_meal_plan,
    generate_sport_recommendations,
)
from src.config.settings import settings

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

# Programme d'entraînement de base par objectif
BASE_EXERCISES: dict[str, list[dict]] = {
    "weight_loss": [
        {"name": "Cardio HIIT", "sets": None, "reps": None, "duration_min": 20},
        {"name": "Squats", "sets": 3, "reps": 15, "duration_min": None},
        {"name": "Fentes", "sets": 3, "reps": 12, "duration_min": None},
        {"name": "Gainage planche", "sets": 3, "reps": None, "duration_min": 1},
    ],
    "muscle_gain": [
        {"name": "Développé couché", "sets": 4, "reps": 8, "duration_min": None},
        {"name": "Tractions", "sets": 4, "reps": 6, "duration_min": None},
        {"name": "Squat barre", "sets": 4, "reps": 8, "duration_min": None},
        {"name": "Soulevé de terre", "sets": 3, "reps": 6, "duration_min": None},
    ],
    "endurance": [
        {"name": "Course à pied", "sets": None, "reps": None, "duration_min": 30},
        {"name": "Vélo", "sets": None, "reps": None, "duration_min": 25},
        {"name": "Natation", "sets": None, "reps": None, "duration_min": 30},
    ],
    "general_health": [
        {"name": "Marche rapide", "sets": None, "reps": None, "duration_min": 20},
        {"name": "Yoga", "sets": None, "reps": None, "duration_min": 20},
        {"name": "Pompes", "sets": 3, "reps": 10, "duration_min": None},
        {"name": "Abdominaux", "sets": 3, "reps": 15, "duration_min": None},
    ],
}

DAYS_OF_WEEK = ["Lundi", "Mercredi", "Vendredi", "Mardi", "Jeudi", "Samedi", "Dimanche"]


@router.post(
    "/recommendations/nutrition",
    response_model=NutritionRecommendationResponse,
    summary="Recommandations nutritionnelles personnalisées",
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def nutrition_recommendations(
    request: Request,
    body: NutritionRecommendationRequest,
    x_user_id: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
    _: str = AuthDep,
):
    profile = body.profile
    daily_targets = calculate_daily_targets(
        weight_kg=profile.weight_kg,
        goal=profile.goal.value,
        fitness_level=profile.fitness_level.value,
    )

    imbalances = detect_imbalances_from_current(body.current_macros, daily_targets)

    recommendations, model = await generate_nutrition_recommendations(
        profile=profile.model_dump(),
        macros=body.current_macros or {},
        imbalances=imbalances,
        daily_targets=daily_targets,
    )

    meal_plan_data, _ = await generate_meal_plan(
        profile=profile.model_dump(),
        daily_targets=daily_targets,
    )

    meal_plan = [MealPlan(**day) for day in meal_plan_data if isinstance(day, dict)]

    result = NutritionRecommendationResponse(
        daily_targets=daily_targets,
        meal_plan=meal_plan,
        recommendations=recommendations,
        model_used=model,
    )

    # Persistance MongoDB (best-effort)
    try:
        await save_recommendation(RecommendationDocument(
            user_id=x_user_id,
            session_id=x_session_id or str(uuid.uuid4()),
            type="nutrition",
            profile_snapshot=profile.model_dump(),
            daily_targets=daily_targets,
            meal_plan=[m.model_dump() for m in meal_plan],
            recommendations=recommendations,
            model_used=model,
        ))
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder la recommandation nutrition: {e}")

    return result


@router.post(
    "/recommendations/sport",
    response_model=SportRecommendationResponse,
    summary="Programme sportif personnalisé",
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def sport_recommendations(
    request: Request,
    body: SportRecommendationRequest,
    x_user_id: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
    _: str = AuthDep,
):
    profile = body.profile
    goal = profile.goal.value

    exercises = BASE_EXERCISES.get(goal, BASE_EXERCISES["general_health"])

    if body.injuries:
        exercises = _filter_exercises_for_injuries(exercises, body.injuries)

    weekly_program = [
        ExerciseSession(
            name=f"Séance {i + 1} - {DAYS_OF_WEEK[i]}",
            duration_min=body.session_duration_min,
            exercises=exercises,
            intensity=_get_intensity(profile.fitness_level.value),
        )
        for i in range(body.sessions_per_week)
    ]

    recommendations, progression_notes, model = await generate_sport_recommendations(
        profile={**profile.model_dump(), "injuries": body.injuries},
        program={"sessions": body.sessions_per_week, "exercises": [e["name"] for e in exercises]},
    )

    result = SportRecommendationResponse(
        weekly_program=weekly_program,
        recommendations=recommendations,
        progression_notes=progression_notes,
        model_used=model,
    )

    # Persistance MongoDB (best-effort)
    try:
        await save_recommendation(RecommendationDocument(
            user_id=x_user_id,
            session_id=x_session_id or str(uuid.uuid4()),
            type="sport",
            profile_snapshot=profile.model_dump(),
            weekly_program=[s.model_dump() for s in weekly_program],
            recommendations=recommendations,
            model_used=model,
        ))
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder la recommandation sport: {e}")

    return result


@router.get(
    "/recommendations/history",
    summary="Historique des recommandations d'un utilisateur",
)
async def get_recommendation_history(
    x_user_id: str = Header(..., description="ID utilisateur du backend TPRE501"),
    type: str | None = None,
    limit: int = 10,
    _: str = AuthDep,
):
    return await get_recommendations_by_user(x_user_id, rec_type=type, limit=limit)


def detect_imbalances_from_current(current_macros: dict | None, targets: dict) -> list[str]:
    """Détecte les déséquilibres si les macros actuelles sont fournies."""
    if not current_macros:
        return []
    imbalances = []
    for key in ("calories", "proteins_g", "carbs_g", "fats_g"):
        if key in current_macros and key in targets:
            ratio = current_macros[key] / targets[key] if targets[key] else 0
            if ratio > 1.3:
                imbalances.append(f"Excès de {key.replace('_g', '').replace('_', ' ')}")
            elif ratio < 0.6:
                imbalances.append(f"Déficit de {key.replace('_g', '').replace('_', ' ')}")
    return imbalances


def _filter_exercises_for_injuries(exercises: list[dict], injuries: list[str]) -> list[dict]:
    """Retire les exercices contre-indiqués selon les blessures déclarées."""
    injury_restrictions = {
        "dos": ["soulevé de terre", "squat barre"],
        "genou": ["squats", "fentes", "course"],
        "épaule": ["développé couché", "tractions", "pompes"],
    }
    excluded = set()
    for injury in injuries:
        for keyword, restricted in injury_restrictions.items():
            if keyword in injury.lower():
                excluded.update(r.lower() for r in restricted)

    return [e for e in exercises if e["name"].lower() not in excluded] or exercises


def _get_intensity(fitness_level: str) -> str:
    return {"beginner": "Faible", "intermediate": "Modérée", "advanced": "Élevée"}.get(
        fitness_level, "Modérée"
    )
