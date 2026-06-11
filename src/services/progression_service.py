"""
Service de progression adaptative et rotation des exercices.

Logique :
  - Chaque semaine, la charge/intensité augmente de 5-10% (surcharge progressive)
  - Les exercices tournent pour cibler tous les groupes musculaires
  - Si l'utilisateur a des séances MariaDB récentes → on adapte depuis son vrai niveau
  - Le programme est sauvegardé en MongoDB pour comparer semaine après semaine
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.repositories.mariadb_repository import get_sport_history, get_available_exercises
from src.repositories.recommendation_repository import get_latest_recommendation
from src.core.database import get_db

logger = logging.getLogger(__name__)

# Groupes musculaires en rotation (push / pull / legs / full body)
# Valeurs exactes de body_part_principale dans la table exercice MariaDB
ROTATION_SPLITS = {
    3: [
        {"label": "Haut du corps - Poussée", "body_parts": ["chest", "shoulders", "upper arms"]},
        {"label": "Haut du corps - Tirage",  "body_parts": ["back", "upper arms"]},
        {"label": "Bas du corps",             "body_parts": ["upper legs", "lower legs", "waist"]},
    ],
    4: [
        {"label": "Poitrine / Triceps",  "body_parts": ["chest", "upper arms"]},
        {"label": "Dos / Biceps",        "body_parts": ["back", "upper arms"]},
        {"label": "Jambes",              "body_parts": ["upper legs", "lower legs"]},
        {"label": "Épaules / Abdos",     "body_parts": ["shoulders", "waist"]},
    ],
    5: [
        {"label": "Poitrine",    "body_parts": ["chest"]},
        {"label": "Dos",         "body_parts": ["back"]},
        {"label": "Épaules",     "body_parts": ["shoulders"]},
        {"label": "Jambes",      "body_parts": ["upper legs", "lower legs"]},
        {"label": "Bras / Abdos","body_parts": ["upper arms", "waist"]},
    ],
}

# Progression d'intensité selon le niveau
INTENSITY_PROGRESSION = {
    "beginner":     {"sets_add": 0, "reps_add": 2,  "week_threshold": 2},
    "intermediate": {"sets_add": 1, "reps_add": 0,  "week_threshold": 1},
    "advanced":     {"sets_add": 0, "reps_add": 0,  "week_threshold": 1},  # charge +5%
}

INTENSITY_LABELS = {
    "beginner":     ["Faible", "Faible-Modérée", "Modérée"],
    "intermediate": ["Modérée", "Modérée-Élevée", "Élevée"],
    "advanced":     ["Élevée", "Élevée", "Maximale"],
}


async def build_weekly_program(
    utilisateur_id: Optional[int],
    sessions_per_week: int,
    session_duration_min: int,
    fitness_level: str,
    goal: str,
    available_equipment: list[str],
    injuries: list[str],
) -> tuple[list[dict], dict]:
    """
    Construit un programme hebdomadaire intelligent.
    Retourne (programme détaillé, méta-données de progression).
    """
    sessions_per_week = max(1, min(sessions_per_week, 7))
    week_number = await _get_week_number(utilisateur_id)

    # Récupérer le split de rotation adapté
    split = _get_rotation_split(sessions_per_week, goal)

    # Récupérer les exercices déjà faits (pour éviter répétitions)
    recent_exercise_names = await _get_recent_exercise_names(utilisateur_id)

    program = []
    days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_indices = _pick_rest_days(sessions_per_week)

    for i, session_split in enumerate(split):
        day = days[day_indices[i]]
        intensity = _get_intensity_for_week(fitness_level, week_number, i)

        # Chercher des exercices depuis la MariaDB pour ce groupe musculaire
        exercises = await _get_exercises_for_split(
            session_split["body_parts"],
            available_equipment,
            injuries,
            recent_exercise_names,
            count=4,
        )

        # Calculer sets/reps selon progression
        sets, reps = _calculate_sets_reps(fitness_level, week_number, goal)

        program.append({
            "day": day,
            "session_number": i + 1,
            "label": session_split["label"],
            "duration_min": session_duration_min,
            "intensity": intensity,
            "exercises": [
                {
                    "name": ex["nom"],
                    "body_part": ex.get("body_part_principale", ""),
                    "muscle_cible": ex.get("muscle_cible_principal", ""),
                    "equipement": ex.get("equipement_principal", "body weight"),
                    "sets": sets,
                    "reps": reps if ex.get("body_part_principale") not in ("cardio",) else None,
                    "duration_min": 20 if ex.get("body_part_principale") == "cardio" else None,
                }
                for ex in exercises
            ],
        })

    progression_meta = {
        "week_number": week_number,
        "progression_note": _build_progression_note(fitness_level, week_number, goal),
        "next_week_objective": _build_next_week_objective(fitness_level, week_number),
    }

    return program, progression_meta


async def _get_week_number(utilisateur_id: Optional[int]) -> int:
    """
    Détermine à quelle semaine de programme l'utilisateur en est.
    Basé sur l'historique des séances MariaDB ou les recommandations MongoDB.
    """
    if utilisateur_id:
        # Compter les semaines depuis la première séance
        history = await get_sport_history(utilisateur_id, days=365)
        if history:
            try:
                first_date = datetime.fromisoformat(history[-1]["date_seance"])
                weeks = (datetime.now() - first_date).days // 7
                return max(1, min(weeks + 1, 12))  # cap à 12 semaines
            except Exception:
                pass

        # Sinon depuis MongoDB
        last_rec = await get_latest_recommendation(str(utilisateur_id), "sport")
        if last_rec and last_rec.get("weekly_program"):
            meta = last_rec.get("progression_meta", {})
            return min((meta.get("week_number", 1) + 1), 12)

    return 1


async def _get_recent_exercise_names(utilisateur_id: Optional[int]) -> set[str]:
    """Retourne les noms des exercices faits ces 7 derniers jours (pour la rotation)."""
    if not utilisateur_id:
        return set()
    history = await get_sport_history(utilisateur_id, days=7)
    names = set()
    for session in history:
        if session.get("exercices"):
            for ex in session["exercices"].split(", "):
                names.add(ex.strip().lower())
    return names


async def _get_exercises_for_split(
    body_parts: list[str],
    equipment: list[str],
    injuries: list[str],
    exclude_names: set[str],
    count: int,
) -> list[dict]:
    """
    Récupère des exercices depuis la MariaDB pour un groupe musculaire,
    en évitant les exercices récents et contre-indiqués.
    """
    all_exercises = []
    for bp in body_parts:
        exs = await get_available_exercises(body_part=bp, limit=10)
        all_exercises.extend(exs)

    # Filtrer blessures
    injury_keywords = _extract_injury_keywords(injuries)
    filtered = [
        ex for ex in all_exercises
        if ex["nom"].lower() not in exclude_names
        and not any(kw in ex["nom"].lower() for kw in injury_keywords)
    ]

    # Dédupliquer et prendre `count` exercices
    seen = set()
    result = []
    for ex in filtered:
        if ex["nom"] not in seen:
            seen.add(ex["nom"])
            result.append(ex)
        if len(result) >= count:
            break

    # Fallback si pas assez d'exercices dans la BDD
    if len(result) < count:
        result.extend(_fallback_exercises(body_parts, count - len(result)))

    return result[:count]


def _get_rotation_split(sessions_per_week: int, goal: str) -> list[dict]:
    """Retourne le split de rotation adapté au nombre de séances."""
    if goal == "general_health" or sessions_per_week <= 2:
        # Full body pour peu de séances ou santé générale
        return [
            {"label": f"Full Body {i+1}", "body_parts": ["chest", "back", "upper legs", "shoulders"]}
            for i in range(sessions_per_week)
        ]

    if goal == "endurance":
        return [
            {"label": f"Cardio/Endurance {i+1}", "body_parts": ["cardio", "upper legs"]}
            for i in range(sessions_per_week)
        ]

    # Utiliser les splits prédéfinis ou adapter
    available = sorted(ROTATION_SPLITS.keys())
    best_key = min(available, key=lambda k: abs(k - sessions_per_week))
    base_split = ROTATION_SPLITS[best_key]

    # Ajuster si sessions > splits disponibles
    result = []
    for i in range(sessions_per_week):
        result.append(base_split[i % len(base_split)])
    return result


def _calculate_sets_reps(fitness_level: str, week: int, goal: str) -> tuple[int, int]:
    """Calcule sets et reps selon le niveau, la semaine et l'objectif."""
    base = {
        "weight_loss":         (3, 15),
        "muscle_gain":         (4, 8),
        "endurance":           (3, 20),
        "general_health":      (3, 12),
        "nutritional_balance": (3, 12),
    }
    sets, reps = base.get(goal, (3, 12))

    prog = INTENSITY_PROGRESSION.get(fitness_level, INTENSITY_PROGRESSION["beginner"])
    bonus_weeks = (week - 1) // prog["week_threshold"]

    sets = min(sets + prog["sets_add"] * bonus_weeks, 5)
    reps = min(reps + prog["reps_add"] * bonus_weeks, 25)

    return sets, reps


def _get_intensity_for_week(fitness_level: str, week: int, session_index: int) -> str:
    labels = INTENSITY_LABELS.get(fitness_level, INTENSITY_LABELS["beginner"])
    idx = min(week - 1, len(labels) - 1)
    return labels[idx]


def _pick_rest_days(sessions_per_week: int) -> list[int]:
    """Répartit les séances intelligemment dans la semaine avec des jours de repos."""
    distributions = {
        1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4],
        5: [0, 1, 2, 4, 5], 6: [0, 1, 2, 3, 4, 5], 7: list(range(7)),
    }
    return distributions.get(sessions_per_week, list(range(sessions_per_week)))


def _build_progression_note(fitness_level: str, week: int, goal: str) -> str:
    if week == 1:
        return "Semaine de mise en route — concentrez-vous sur la technique avant la charge."
    if week <= 3:
        return f"Semaine {week} — augmentez progressivement l'intensité. Votre corps s'adapte."
    if week <= 6:
        return f"Semaine {week} — vous êtes dans la phase de progression. Restez régulier."
    if week <= 9:
        return f"Semaine {week} — phase avancée. Pensez à une semaine de décharge (volume -30%) à la semaine 8."
    return f"Semaine {week} — excellent travail ! Envisagez un nouveau cycle avec des objectifs révisés."


def _build_next_week_objective(fitness_level: str, week: int) -> str:
    prog = INTENSITY_PROGRESSION.get(fitness_level, INTENSITY_PROGRESSION["beginner"])
    if prog["reps_add"] > 0:
        return f"Semaine prochaine : +{prog['reps_add']} répétition(s) par série."
    if prog["sets_add"] > 0:
        return f"Semaine prochaine : +{prog['sets_add']} série(s) par exercice."
    return "Semaine prochaine : augmentez la charge de 2.5 à 5% si les dernières reps sont faciles."


def _extract_injury_keywords(injuries: list[str]) -> list[str]:
    keywords = []
    injury_map = {
        "dos": ["deadlift", "soulevé", "good morning"],
        "genou": ["squat", "lunge", "fente", "leg press"],
        "épaule": ["press", "développé", "lateral raise", "overhead"],
        "poignet": ["curl", "wrist", "push"],
    }
    for injury in injuries:
        for key, words in injury_map.items():
            if key in injury.lower():
                keywords.extend(words)
    return keywords


def _fallback_exercises(body_parts: list[str], count: int) -> list[dict]:
    """Exercices de secours si la MariaDB ne retourne pas assez de résultats."""
    fallbacks = {
        "chest":      [{"nom": "Pompes", "body_part_principale": "chest", "muscle_cible_principal": "pectoraux", "equipement_principal": "body weight"}],
        "back":       [{"nom": "Tractions", "body_part_principale": "back", "muscle_cible_principal": "dorsaux", "equipement_principal": "body weight"}],
        "upper legs": [{"nom": "Squats", "body_part_principale": "upper legs", "muscle_cible_principal": "quadriceps", "equipement_principal": "body weight"}],
        "shoulders":  [{"nom": "Élévations latérales", "body_part_principale": "shoulders", "muscle_cible_principal": "deltoïdes", "equipement_principal": "dumbbell"}],
        "biceps":     [{"nom": "Curl biceps", "body_part_principale": "biceps", "muscle_cible_principal": "biceps", "equipement_principal": "dumbbell"}],
        "triceps":    [{"nom": "Dips", "body_part_principale": "triceps", "muscle_cible_principal": "triceps", "equipement_principal": "body weight"}],
        "waist":      [{"nom": "Planche", "body_part_principale": "waist", "muscle_cible_principal": "abdominaux", "equipement_principal": "body weight"}],
        "cardio":     [{"nom": "Course à pied", "body_part_principale": "cardio", "muscle_cible_principal": "cardio-vasculaire", "equipement_principal": "body weight"}],
    }
    result = []
    for bp in body_parts:
        result.extend(fallbacks.get(bp, []))
    return result[:count]
