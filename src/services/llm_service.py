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


async def generate_sport_recommendations(
    profile: dict,
    program: dict,
    progression_meta: dict = None,
) -> tuple[list[str], str, str]:
    """
    Génère des recommandations sportives personnalisées.
    Retourne (recommandations, notes de progression, modèle utilisé).
    """
    prompt = _build_sport_prompt(profile, program, progression_meta)
    raw_text, model = await _generate_raw(prompt)
    recommendations, progression = _parse_sport_response(raw_text)
    return recommendations, progression, model


async def _generate_raw(prompt: str) -> tuple[str, str]:
    """Retourne le texte brut généré + le modèle utilisé."""
    result = await _call_ollama_raw(prompt)
    if result:
        return result, settings.OLLAMA_MODEL
    result = await _call_huggingface_raw(prompt)
    if result:
        return result, "huggingface-llm"
    return "\n".join(_fallback_recommendations()), "fallback"


async def _call_ollama_raw(prompt: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            return response.json().get("response", "")
    except Exception as e:
        logger.info(f"Ollama non disponible: {e}")
        return None


async def _call_huggingface_raw(prompt: str) -> str | None:
    if not settings.HF_API_KEY:
        return None
    url = f"{settings.HF_INFERENCE_URL}/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {settings.HF_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json={"inputs": prompt, "parameters": {"max_new_tokens": 512}}, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data[0]["generated_text"] if isinstance(data, list) else ""
    except Exception as e:
        logger.error(f"HuggingFace LLM error: {e}")
        return None


def _parse_sport_response(text: str) -> tuple[list[str], str]:
    """Extrait les recommandations et la note de progression depuis la réponse Ollama."""
    progression = "Augmentez progressivement l'intensité chaque semaine."
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    recommendations = []
    for line in lines:
        if line.upper().startswith("PROGRESSION:"):
            progression = line.split(":", 1)[1].strip()
        else:
            clean = line.lstrip("•-*0123456789. ").strip()
            if len(clean) > 15:
                recommendations.append(clean)

    return recommendations[:5] or _fallback_recommendations(), progression


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
    # Données réelles MariaDB si disponibles
    historique = profile.get("historique_nutrition", {})
    avg_cal = historique.get("avg_calories")
    avg_prot = historique.get("avg_proteines_g")
    sommeil = profile.get("sommeil_moyen_h")
    stress = profile.get("stress_moyen")
    imc = profile.get("imc")

    contexte_reel = ""
    if avg_cal:
        contexte_reel += f"- Moyenne calories 7 derniers jours : {avg_cal:.0f} kcal/jour\n"
    if avg_prot:
        contexte_reel += f"- Moyenne protéines : {avg_prot:.0f}g/jour\n"
    if sommeil:
        contexte_reel += f"- Sommeil moyen : {sommeil:.1f}h/nuit\n"
    if stress:
        contexte_reel += f"- Score de stress moyen : {stress:.1f}/10\n"
    if imc:
        contexte_reel += f"- IMC actuel : {imc:.1f}\n"

    return f"""Tu es un nutritionniste expert. Réponds en français. Donne 5 recommandations concrètes et personnalisées.

PROFIL UTILISATEUR :
- Prénom : {profile.get('prenom', 'Utilisateur')}
- Âge : {profile.get('age', '?')} ans
- Objectif : {profile.get('goal')}
- Poids : {profile.get('weight_kg', '?')} kg
- Allergies : {', '.join(profile.get('allergies', [])) or 'aucune'}
- Budget : {profile.get('budget_per_day_eur', 'non précisé')}€/jour

DONNÉES RÉELLES (7 derniers jours) :
{contexte_reel or '- Aucun historique disponible'}

REPAS ANALYSÉ :
- Macros : {macros}
- Déséquilibres : {', '.join(imbalances) or 'aucun'}

CIBLES JOURNALIÈRES CALCULÉES :
{targets}

Donne exactement 5 recommandations courtes, actionnables et basées sur les données réelles (une par ligne, commence par un verbe)."""


def _build_meal_plan_prompt(profile: dict, targets: dict) -> str:
    historique = profile.get("historique_nutrition", {})
    aliments_frequents = profile.get("aliments_frequents", [])

    return f"""Tu es un nutritionniste expert. Génère un plan de repas pour 3 jours en JSON. Réponds uniquement avec le JSON.

PROFIL :
- Objectif : {profile.get('goal')}
- Allergies : {', '.join(profile.get('allergies', [])) or 'aucune'}
- Budget : {profile.get('budget_per_day_eur', 15)}€/jour
- Préférences connues : {', '.join(aliments_frequents) or 'aucune'}

CIBLES NUTRITIONNELLES :
- Calories : {targets.get('calories')} kcal
- Protéines : {targets.get('proteins_g')}g
- Glucides : {targets.get('carbs_g')}g
- Lipides : {targets.get('fats_g')}g

FORMAT JSON ATTENDU (réponds UNIQUEMENT avec ce JSON) :
[{{"day": "Lundi", "meals": [{{"name": "Petit-déjeuner", "description": "Détail du repas"}}, {{"name": "Déjeuner", "description": "..."}}, {{"name": "Dîner", "description": "..."}}], "total_macros": {{"calories": 0, "proteins_g": 0, "carbs_g": 0, "fats_g": 0}}}}]"""


def _build_sport_prompt(profile: dict, program: dict, progression_meta: dict = None) -> str:
    historique_sport = profile.get("historique_sport", [])
    nb_seances_recentes = len(historique_sport)
    week_number = (progression_meta or {}).get("week_number", 1)

    contexte_sport = ""
    if nb_seances_recentes > 0:
        types = list({s.get("type_entrainement", "") for s in historique_sport if s.get("type_entrainement")})
        cal_moy = sum(float(s.get("calories_brulees_total") or 0) for s in historique_sport) / nb_seances_recentes
        contexte_sport += f"- {nb_seances_recentes} séances effectuées ces 30 derniers jours\n"
        contexte_sport += f"- Types d'entraînement : {', '.join(types) or 'varié'}\n"
        if cal_moy > 0:
            contexte_sport += f"- Calories brûlées en moyenne : {cal_moy:.0f} kcal/séance\n"

    return f"""Tu es un coach sportif expert. Réponds en français. Donne 5 conseils personnalisés + 1 note de progression.

PROFIL :
- Prénom : {profile.get('prenom', 'Utilisateur')}
- Objectif : {profile.get('goal')}
- Niveau : {profile.get('fitness_level')}
- Blessures/limitations : {', '.join(profile.get('injuries', [])) or 'aucune'}
- Semaine de programme : {week_number}

HISTORIQUE RÉEL (30 derniers jours) :
{contexte_sport or '- Aucun historique disponible'}

PROGRAMME CETTE SEMAINE :
- Séances : {program.get('sessions')} fois/semaine
- Exercices : {', '.join(program.get('exercises', [])[:6])}

Donne exactement 5 conseils pratiques numérotés, puis sur la dernière ligne : "PROGRESSION: [note sur l'évolution attendue]"."""
