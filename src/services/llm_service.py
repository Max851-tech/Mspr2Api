"""
Service LLM pour la génération de recommandations personnalisées.
Priorité : Ollama (local) → HuggingFace Inference API
"""
import httpx
import json
import logging

from src.config.settings import settings

logger = logging.getLogger(__name__)


async def generate_nutrition_recommendations(
    profile: dict,
    macros: dict,
    imbalances: list[str],
    daily_targets: dict,
) -> tuple[list[str], str]:
    """
    Génère des recommandations nutritionnelles personnalisées.
    Retourne (liste de recommandations, modèle utilisé).
    """
    prompt = _build_nutrition_prompt(profile, macros, imbalances, daily_targets)
    return await _generate(prompt)


async def generate_meal_plan(profile: dict, daily_targets: dict) -> tuple[list[dict], str]:
    """Génère un plan de repas hebdomadaire personnalisé."""
    prompt = _build_meal_plan_prompt(profile, daily_targets)
    raw, model = await _generate(prompt, expect_json=True)
    try:
        plan = json.loads(raw[0]) if isinstance(raw, list) else []
    except (json.JSONDecodeError, IndexError):
        plan = _fallback_meal_plan(daily_targets)
    return plan, model


async def generate_sport_recommendations(profile: dict, program: dict) -> tuple[list[str], str, str]:
    """
    Génère des recommandations sportives personnalisées.
    Retourne (recommandations, notes de progression, modèle utilisé).
    """
    prompt = _build_sport_prompt(profile, program)
    recommendations, model = await _generate(prompt)
    progression = recommendations[-1] if len(recommendations) > 3 else "Augmentez progressivement l'intensité chaque semaine."
    return recommendations[:-1], progression, model


async def _generate(prompt: str, expect_json: bool = False) -> tuple[list[str] | str, str]:
    """Appelle Ollama ou HuggingFace selon la disponibilité."""
    result = await _call_ollama(prompt, expect_json)
    if result is not None:
        return result, settings.OLLAMA_MODEL

    result = await _call_huggingface(prompt)
    if result is not None:
        return result, "huggingface-llm"

    return _fallback_recommendations(), "fallback"


async def _call_ollama(prompt: str, expect_json: bool = False) -> list[str] | None:
    """Appel à Ollama en local."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json" if expect_json else None,
                },
            )
            response.raise_for_status()
            text = response.json().get("response", "")
            return [text] if expect_json else _parse_recommendations(text)
    except Exception as e:
        logger.info(f"Ollama non disponible: {e}")
        return None


async def _call_huggingface(prompt: str) -> list[str] | None:
    """Appel à un modèle texte HuggingFace (ex: mistralai/Mistral-7B-Instruct)."""
    if not settings.HF_API_KEY:
        return None

    url = f"{settings.HF_INFERENCE_URL}/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {settings.HF_API_KEY}"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 512, "temperature": 0.7}}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            text = data[0]["generated_text"] if isinstance(data, list) else ""
            return _parse_recommendations(text)
    except Exception as e:
        logger.error(f"HuggingFace LLM error: {e}")
        return None


def _parse_recommendations(text: str) -> list[str]:
    """Extrait une liste de recommandations depuis un texte libre."""
    lines = [line.strip().lstrip("•-*123456789. ") for line in text.split("\n")]
    return [line for line in lines if len(line) > 20][:6] or _fallback_recommendations()


def _fallback_recommendations() -> list[str]:
    return [
        "Variez vos sources de protéines (légumineuses, viande maigre, œufs).",
        "Privilégiez les glucides complexes (riz complet, patate douce, avoine).",
        "Intégrez des légumes verts à chaque repas pour les fibres et micronutriments.",
        "Hydratez-vous avec 1,5 à 2L d'eau par jour.",
        "Limitez les aliments ultra-transformés et les sucres ajoutés.",
    ]


def _fallback_meal_plan(targets: dict) -> list[dict]:
    return [
        {
            "day": "Lundi",
            "meals": [
                {"name": "Petit-déjeuner", "description": "Flocons d'avoine, fruits rouges, yaourt grec"},
                {"name": "Déjeuner", "description": "Poulet grillé, riz complet, légumes vapeur"},
                {"name": "Dîner", "description": "Saumon, patate douce, salade verte"},
            ],
            "total_macros": targets,
        }
    ]


def _build_nutrition_prompt(profile: dict, macros: dict, imbalances: list, targets: dict) -> str:
    return f"""Tu es un nutritionniste expert. Analyse ce repas et donne 5 recommandations concrètes.

Profil utilisateur:
- Objectif: {profile.get('goal')}
- Allergies: {', '.join(profile.get('allergies', [])) or 'aucune'}
- Budget/jour: {profile.get('budget_per_day_eur', 'non précisé')}€

Macros du repas: {macros}
Déséquilibres détectés: {', '.join(imbalances) or 'aucun'}
Cibles journalières: {targets}

Donne 5 recommandations pratiques, courtes et actionnables (une par ligne)."""


def _build_meal_plan_prompt(profile: dict, targets: dict) -> str:
    return f"""Génère un plan de repas pour 3 jours en JSON.
Profil: objectif={profile.get('goal')}, allergies={profile.get('allergies', [])}, budget={profile.get('budget_per_day_eur')}€/jour
Cibles: {targets}
Format JSON: [{{"day": "Lundi", "meals": [{{"name": "...", "description": "..."}}], "total_macros": {{}}}}]"""


def _build_sport_prompt(profile: dict, program: dict) -> str:
    return f"""Tu es un coach sportif expert. Donne 5 recommandations pour ce programme.

Profil: objectif={profile.get('goal')}, niveau={profile.get('fitness_level')}, blessures={profile.get('injuries', [])}
Programme: {program}

Donne 5 conseils pratiques + 1 note sur la progression (une par ligne)."""
