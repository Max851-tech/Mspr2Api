"""
Service nutritionnel : calcul des macros et détection des déséquilibres.
Source de données : USDA FoodData Central API (gratuit).
"""
import httpx
import logging
from typing import Optional

from src.config.settings import settings
from src.models.food import DetectedFood, Macros

logger = logging.getLogger(__name__)

# Valeurs nutritionnelles de référence pour 100g (fallback local)
NUTRITION_FALLBACK: dict[str, dict] = {
    "pizza": {"calories": 266, "proteins_g": 11, "carbs_g": 33, "fats_g": 10, "fiber_g": 2.3},
    "salad": {"calories": 20, "proteins_g": 1.5, "carbs_g": 3, "fats_g": 0.3, "fiber_g": 2},
    "chicken": {"calories": 165, "proteins_g": 31, "carbs_g": 0, "fats_g": 3.6, "fiber_g": 0},
    "rice": {"calories": 130, "proteins_g": 2.7, "carbs_g": 28, "fats_g": 0.3, "fiber_g": 0.4},
    "pasta": {"calories": 157, "proteins_g": 5.8, "carbs_g": 31, "fats_g": 0.9, "fiber_g": 1.8},
    "burger": {"calories": 295, "proteins_g": 17, "carbs_g": 24, "fats_g": 14, "fiber_g": 1.3},
    "sushi": {"calories": 143, "proteins_g": 5.8, "carbs_g": 20, "fats_g": 4, "fiber_g": 0.6},
    "steak": {"calories": 271, "proteins_g": 26, "carbs_g": 0, "fats_g": 18, "fiber_g": 0},
    "default": {"calories": 150, "proteins_g": 5, "carbs_g": 20, "fats_g": 5, "fiber_g": 1},
}

# DRI quotidiens de référence (adulte 70kg moyen)
DAILY_REFERENCE = {
    "calories": 2000,
    "proteins_g": 50,
    "carbs_g": 260,
    "fats_g": 65,
    "fiber_g": 28,
}


async def get_macros_for_foods(foods: list[DetectedFood]) -> Macros:
    """Calcule les macros totales pour une liste d'aliments détectés."""
    totals = {"calories": 0.0, "proteins_g": 0.0, "carbs_g": 0.0, "fats_g": 0.0, "fiber_g": 0.0}

    for food in foods:
        # Quantité estimée : 150g si non précisée (portion standard)
        quantity = food.quantity_g or 150.0
        nutrition = await _fetch_nutrition(food.name)

        factor = quantity / 100.0
        for key in totals:
            totals[key] += nutrition.get(key, 0) * factor

    return Macros(**{k: round(v, 1) for k, v in totals.items()})


def detect_imbalances(macros: Macros) -> list[str]:
    """Détecte les déséquilibres nutritionnels par rapport aux références quotidiennes."""
    imbalances = []
    ref = DAILY_REFERENCE

    # Calcul de la part de ce repas (~30% du quota journalier pour un repas)
    meal_factor = 0.30

    if macros.calories > ref["calories"] * meal_factor * 1.4:
        imbalances.append("Apport calorique élevé pour ce repas")
    elif macros.calories < ref["calories"] * meal_factor * 0.5:
        imbalances.append("Apport calorique insuffisant pour ce repas")

    if macros.proteins_g < ref["proteins_g"] * meal_factor * 0.6:
        imbalances.append("Faible apport en protéines")

    if macros.fats_g > ref["fats_g"] * meal_factor * 1.5:
        imbalances.append("Excès de graisses")

    if macros.fiber_g < 3:
        imbalances.append("Manque de fibres alimentaires")

    if macros.carbs_g > ref["carbs_g"] * meal_factor * 1.5:
        imbalances.append("Excès de glucides")

    return imbalances


def calculate_daily_targets(weight_kg: float, goal: str, fitness_level: str) -> dict:
    """Calcule les cibles nutritionnelles journalières personnalisées (formule de Harris-Benedict)."""
    # Base : 1800 kcal pour simplifier (à ajuster selon BMR réel)
    bmr = 10 * weight_kg + 500  # approximation simplifiée

    multipliers = {
        "weight_loss": 0.85,
        "muscle_gain": 1.15,
        "endurance": 1.10,
        "general_health": 1.0,
        "nutritional_balance": 1.0,
    }
    factor = multipliers.get(goal, 1.0)
    calories = round(bmr * factor)

    protein_factor = 1.6 if goal == "muscle_gain" else 1.2
    proteins = round(weight_kg * protein_factor)
    fats = round(calories * 0.25 / 9)
    carbs = round((calories - proteins * 4 - fats * 9) / 4)
    fiber = 30 if goal in ("nutritional_balance", "weight_loss") else 25

    return {
        "calories": calories,
        "proteins_g": proteins,
        "carbs_g": carbs,
        "fats_g": fats,
        "fiber_g": fiber,
    }


async def _fetch_nutrition(food_name: str) -> dict:
    """
    Récupère les données nutritionnelles dans cet ordre de priorité :
    1. Table `aliment` MariaDB (données locales, fiables, déjà nettoyées)
    2. Fallback dictionnaire local
    3. API USDA FoodData Central (si rien d'autre ne fonctionne)
    """
    # 1. Recherche dans la table aliment de la MariaDB
    from src.repositories.mariadb_repository import search_aliment
    results = await search_aliment(food_name, limit=1)
    if results:
        r = results[0]
        return {
            "calories": r.get("calories_kcal", 150),
            "proteins_g": r.get("proteines_g", 5),
            "carbs_g": r.get("glucides_g", 20),
            "fats_g": r.get("lipides_g", 5),
            "fiber_g": r.get("fibres_g", 1),
        }

    # 2. Fallback dictionnaire local
    for key in NUTRITION_FALLBACK:
        if key in food_name.lower():
            return NUTRITION_FALLBACK[key]

    # 3. API USDA FoodData Central
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.USDA_BASE_URL}/foods/search",
                params={"query": food_name, "pageSize": 1, "api_key": settings.USDA_API_KEY},
            )
            response.raise_for_status()
            data = response.json()

        if not data.get("foods"):
            return NUTRITION_FALLBACK["default"]

        food_data = data["foods"][0]
        nutrients = {n["nutrientName"]: n["value"] for n in food_data.get("foodNutrients", [])}

        return {
            "calories": nutrients.get("Energy", 150),
            "proteins_g": nutrients.get("Protein", 5),
            "carbs_g": nutrients.get("Carbohydrate, by difference", 20),
            "fats_g": nutrients.get("Total lipid (fat)", 5),
            "fiber_g": nutrients.get("Fiber, total dietary", 1),
        }
    except Exception as e:
        logger.warning(f"USDA fetch failed for '{food_name}': {e}")
        return NUTRITION_FALLBACK["default"]
