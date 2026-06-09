import uuid
import logging
from fastapi import APIRouter, UploadFile, File, Request, Header
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.dependencies import AuthDep
from src.models.food import FoodAnalysisResponse
from src.models.db_documents import FoodAnalysisDocument
from src.services.vision_service import analyze_food_image
from src.services.nutrition_service import get_macros_for_foods, detect_imbalances, calculate_daily_targets
from src.services.llm_service import generate_nutrition_recommendations
from src.repositories.food_repository import save_analysis
from src.utils.validators import validate_image
from src.utils.image_processing import preprocess_image
from src.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/analyze",
    response_model=FoodAnalysisResponse,
    summary="Analyser une photo de repas",
    description="Identifie les aliments, calcule les macros et génère des recommandations personnalisées.",
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def analyze_meal(
    request: Request,
    file: UploadFile = File(..., description="Photo du repas (JPEG, PNG, WebP, max 10MB)"),
    x_user_id: str | None = Header(default=None, description="ID utilisateur du backend TPRE501"),
    x_session_id: str | None = Header(default=None, description="ID de session anonyme"),
    _: str = AuthDep,
):
    # 1. Validation et prétraitement de l'image
    raw_bytes = await validate_image(file)
    image_bytes = preprocess_image(raw_bytes)

    # 2. Détection visuelle des aliments
    detected_foods, source = await analyze_food_image(image_bytes)

    # 3. Calcul des macros
    macros = await get_macros_for_foods(detected_foods)

    # 4. Détection des déséquilibres
    imbalances = detect_imbalances(macros)

    # 5. Suggestions personnalisées
    suggestions, _ = await generate_nutrition_recommendations(
        profile={"goal": "general_health", "allergies": []},
        macros=macros.model_dump(),
        imbalances=imbalances,
        daily_targets=calculate_daily_targets(70, "general_health", "beginner"),
    )

    result = FoodAnalysisResponse(
        detected_foods=detected_foods,
        total_macros=macros,
        imbalances=imbalances,
        suggestions=suggestions,
        analysis_source=source,
    )

    # 6. Persistance MongoDB (best-effort — ne bloque pas la réponse)
    try:
        await save_analysis(FoodAnalysisDocument(
            user_id=x_user_id,
            session_id=x_session_id or str(uuid.uuid4()),
            detected_foods=[f.model_dump() for f in detected_foods],
            total_macros=macros.model_dump(),
            imbalances=imbalances,
            suggestions=suggestions,
            analysis_source=source,
        ))
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder l'analyse en base: {e}")

    return result


@router.get(
    "/analyze/history",
    summary="Historique des analyses d'un utilisateur",
)
async def get_analysis_history(
    x_user_id: str = Header(..., description="ID utilisateur du backend TPRE501"),
    limit: int = 20,
    _: str = AuthDep,
):
    from src.repositories.food_repository import get_analyses_by_user
    return await get_analyses_by_user(x_user_id, limit=limit)
