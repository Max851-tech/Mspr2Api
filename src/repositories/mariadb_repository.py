"""
Requêtes en lecture sur la BDD MariaDB existante (TPRE501 - healthai_coaching).
Aucune écriture — l'ai-service est en lecture seule sur cette base.

Tables utilisées :
  - utilisateur            → profil de base
  - objectif_utilisateur   → objectif santé actif
  - mesure_biometrique     → dernière mesure (poids, IMC, BPM)
  - mesure_sommeil_sante   → stress, sommeil, activité physique
  - journal_alimentaire    → historique alimentaire
  - aliment                → données nutritionnelles (macros réelles)
  - plat                   → repas composés
  - seance_entrainement    → historique sport
  - seance_exercice        → exercices par séance
  - exercice               → catalogue d'exercices
"""
import logging
from typing import Optional
from datetime import date, timedelta

from src.core.mariadb import get_pool, is_available

logger = logging.getLogger(__name__)

# Mapping objectif MariaDB → objectif ai-service
OBJECTIF_MAP = {
    "PERTE_POIDS": "weight_loss",
    "GAIN_MUSCLE": "muscle_gain",
    "SOMMEIL": "general_health",
    "EQUILIBRE_VIE": "nutritional_balance",
    "MAINTIEN_FORME": "general_health",
    "AUTRE": "general_health",
}


async def get_user_full_profile(utilisateur_id: int) -> Optional[dict]:
    """
    Construit un profil utilisateur complet pour l'IA en combinant :
    utilisateur + objectif actif + dernière mesure biométrique + données sommeil récentes.
    Retourne None si MariaDB n'est pas disponible ou si l'utilisateur n'existe pas.
    """
    if not is_available():
        return None

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Infos de base utilisateur
                await cur.execute(
                    """
                    SELECT u.utilisateur_id, u.prenom, u.nom, u.date_naissance,
                           u.genre, u.taille_cm, u.email
                    FROM utilisateur u
                    WHERE u.utilisateur_id = %s AND u.statut = 'ACTIF'
                    """,
                    (utilisateur_id,),
                )
                user = await cur.fetchone()
                if not user:
                    return None

                # Calcul de l'âge depuis date_naissance
                age = None
                if user["date_naissance"]:
                    today = date.today()
                    dob = user["date_naissance"]
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

                # Objectif actif
                await cur.execute(
                    """
                    SELECT type_objectif FROM objectif_utilisateur
                    WHERE utilisateur_id = %s AND actif_unique = 1
                    ORDER BY date_debut DESC LIMIT 1
                    """,
                    (utilisateur_id,),
                )
                objectif_row = await cur.fetchone()
                goal_raw = objectif_row["type_objectif"] if objectif_row else "MAINTIEN_FORME"
                goal = OBJECTIF_MAP.get(goal_raw, "general_health")

                # Dernière mesure biométrique
                await cur.execute(
                    """
                    SELECT poids_kg, taille_cm, imc, taux_masse_grasse,
                           bpm_repos, eau_l, mesure_le
                    FROM mesure_biometrique
                    WHERE utilisateur_id = %s
                    ORDER BY mesure_le DESC LIMIT 1
                    """,
                    (utilisateur_id,),
                )
                bio = await cur.fetchone()

                # Données sommeil/santé récentes (30 derniers jours)
                await cur.execute(
                    """
                    SELECT AVG(stress_score) as stress_moyen,
                           AVG(duree_sommeil_h) as sommeil_moyen_h,
                           AVG(activite_physique_min_jour) as activite_moy_min,
                           AVG(frequence_cardiaque_bpm) as bpm_moyen
                    FROM mesure_sommeil_sante
                    WHERE utilisateur_id = %s
                      AND mesure_le >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    """,
                    (utilisateur_id,),
                )
                sante = await cur.fetchone()

                # Niveau d'expérience sport (depuis les dernières séances)
                await cur.execute(
                    """
                    SELECT niveau_experience FROM seance_entrainement
                    WHERE utilisateur_id = %s AND niveau_experience IS NOT NULL
                    ORDER BY date_seance DESC LIMIT 1
                    """,
                    (utilisateur_id,),
                )
                exp_row = await cur.fetchone()
                fitness_level = _map_fitness_level(
                    exp_row["niveau_experience"] if exp_row else None
                )

                return {
                    "utilisateur_id": utilisateur_id,
                    "prenom": user["prenom"],
                    "nom": user["nom"],
                    "email": user["email"],
                    "age": age or 25,
                    "genre": user["genre"],
                    "taille_cm": float(bio["taille_cm"] or user["taille_cm"] or 170) if bio else float(user["taille_cm"] or 170),
                    "weight_kg": float(bio["poids_kg"]) if bio and bio["poids_kg"] else 70.0,
                    "imc": float(bio["imc"]) if bio and bio["imc"] else None,
                    "taux_masse_grasse": float(bio["taux_masse_grasse"]) if bio and bio["taux_masse_grasse"] else None,
                    "bpm_repos": bio["bpm_repos"] if bio else None,
                    "goal": goal,
                    "fitness_level": fitness_level,
                    "stress_moyen": float(sante["stress_moyen"]) if sante and sante["stress_moyen"] else None,
                    "sommeil_moyen_h": float(sante["sommeil_moyen_h"]) if sante and sante["sommeil_moyen_h"] else None,
                    "activite_moy_min_jour": float(sante["activite_moy_min"]) if sante and sante["activite_moy_min"] else None,
                    # Allergies/préférences non présentes dans la BDD → à fournir via requête
                    "allergies": [],
                    "dietary_preferences": [],
                    "budget_per_day_eur": None,
                    "injuries": [],
                }
    except Exception as e:
        logger.error(f"Erreur lecture profil utilisateur {utilisateur_id}: {e}")
        return None


async def get_nutrition_history(utilisateur_id: int, days: int = 7) -> list[dict]:
    """
    Retourne l'historique alimentaire des N derniers jours avec les macros réelles
    depuis journal_alimentaire + aliment.
    """
    if not is_available():
        return []

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT
                        j.consomme_le,
                        j.type_repas,
                        COALESCE(a.nom, j.aliment_nom_libre, p.nom_plat) AS aliment_nom,
                        j.quantite,
                        j.unite_quantite,
                        COALESCE(j.calories_kcal,
                            a.calories_kcal * j.quantite / 100,
                            p.calories_totales_kcal
                        ) AS calories_kcal,
                        a.proteines_g * j.quantite / 100 AS proteines_g,
                        a.glucides_g * j.quantite / 100 AS glucides_g,
                        a.lipides_g * j.quantite / 100 AS lipides_g,
                        a.fibres_g * j.quantite / 100 AS fibres_g
                    FROM journal_alimentaire j
                    LEFT JOIN aliment a ON j.aliment_id = a.aliment_id
                    LEFT JOIN plat p ON j.plat_id = p.plat_id
                    WHERE j.utilisateur_id = %s
                      AND j.consomme_le >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    ORDER BY j.consomme_le DESC
                    """,
                    (utilisateur_id, days),
                )
                rows = await cur.fetchall()
                return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"Erreur lecture historique nutrition {utilisateur_id}: {e}")
        return []


async def get_daily_macros_summary(utilisateur_id: int, days: int = 7) -> dict:
    """
    Calcule les moyennes de macros sur les N derniers jours.
    Utile pour personnaliser les recommandations nutrition.
    """
    if not is_available():
        return {}

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT
                        AVG(COALESCE(j.calories_kcal, a.calories_kcal * j.quantite / 100)) AS avg_calories,
                        AVG(a.proteines_g * j.quantite / 100) AS avg_proteines_g,
                        AVG(a.glucides_g * j.quantite / 100) AS avg_glucides_g,
                        AVG(a.lipides_g * j.quantite / 100) AS avg_lipides_g,
                        AVG(a.fibres_g * j.quantite / 100) AS avg_fibres_g,
                        COUNT(DISTINCT DATE(j.consomme_le)) AS jours_avec_donnees
                    FROM journal_alimentaire j
                    LEFT JOIN aliment a ON j.aliment_id = a.aliment_id
                    WHERE j.utilisateur_id = %s
                      AND j.consomme_le >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    """,
                    (utilisateur_id, days),
                )
                row = await cur.fetchone()
                if not row or row["jours_avec_donnees"] == 0:
                    return {}
                return {
                    "avg_calories": float(row["avg_calories"] or 0),
                    "avg_proteines_g": float(row["avg_proteines_g"] or 0),
                    "avg_glucides_g": float(row["avg_glucides_g"] or 0),
                    "avg_lipides_g": float(row["avg_lipides_g"] or 0),
                    "avg_fibres_g": float(row["avg_fibres_g"] or 0),
                    "jours_avec_donnees": row["jours_avec_donnees"],
                }
    except Exception as e:
        logger.error(f"Erreur résumé macros {utilisateur_id}: {e}")
        return {}


async def get_sport_history(utilisateur_id: int, days: int = 30) -> list[dict]:
    """
    Retourne l'historique des séances d'entraînement avec les exercices détaillés.
    """
    if not is_available():
        return []

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT
                        s.seance_id,
                        s.date_seance,
                        s.type_entrainement,
                        s.duree_seance_min,
                        s.calories_brulees_total,
                        s.niveau_experience,
                        GROUP_CONCAT(e.nom ORDER BY se.ordre_exercice SEPARATOR ', ') AS exercices,
                        GROUP_CONCAT(e.body_part_principale ORDER BY se.ordre_exercice SEPARATOR ', ') AS parties_corps,
                        GROUP_CONCAT(e.equipement_principal ORDER BY se.ordre_exercice SEPARATOR ', ') AS equipements
                    FROM seance_entrainement s
                    LEFT JOIN seance_exercice se ON s.seance_id = se.seance_id
                    LEFT JOIN exercice e ON se.exercice_id = e.exercice_id
                    WHERE s.utilisateur_id = %s
                      AND s.date_seance >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    GROUP BY s.seance_id
                    ORDER BY s.date_seance DESC
                    """,
                    (utilisateur_id, days),
                )
                rows = await cur.fetchall()
                return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"Erreur lecture historique sport {utilisateur_id}: {e}")
        return []


async def get_available_exercises(
    body_part: str | None = None,
    equipment: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Récupère des exercices depuis le catalogue (table exercice).
    Filtrable par partie du corps et équipement disponible.
    """
    if not is_available():
        return []

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                conditions = []
                params = []

                if body_part:
                    conditions.append("body_part_principale = %s")
                    params.append(body_part)
                if equipment:
                    conditions.append("equipement_principal = %s")
                    params.append(equipment)

                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                params.append(limit)

                await cur.execute(
                    f"""
                    SELECT exercice_id, nom, body_part_principale,
                           muscle_cible_principal, equipement_principal
                    FROM exercice
                    {where}
                    ORDER BY RAND()
                    LIMIT %s
                    """,
                    params,
                )
                rows = await cur.fetchall()
                return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"Erreur lecture exercices: {e}")
        return []


async def search_aliment(nom: str, limit: int = 5) -> list[dict]:
    """
    Recherche un aliment dans la table aliment (utilisé en fallback local
    avant d'appeler l'API USDA).
    """
    if not is_available():
        return []

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT nom, categorie, calories_kcal, proteines_g,
                           glucides_g, lipides_g, fibres_g, sucres_g, sodium_mg
                    FROM aliment
                    WHERE nom LIKE %s
                    LIMIT %s
                    """,
                    (f"%{nom}%", limit),
                )
                rows = await cur.fetchall()
                return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.error(f"Erreur recherche aliment '{nom}': {e}")
        return []


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _map_fitness_level(niveau: str | None) -> str:
    """Convertit le niveau d'expérience MariaDB vers les niveaux de l'ai-service."""
    if not niveau:
        return "beginner"
    niveau = niveau.lower()
    if any(k in niveau for k in ("débutant", "debutant", "beginner", "novice")):
        return "beginner"
    if any(k in niveau for k in ("intermédiaire", "intermediaire", "intermediate", "moyen")):
        return "intermediate"
    if any(k in niveau for k in ("avancé", "avance", "advanced", "expert", "confirmé")):
        return "advanced"
    return "beginner"


def _serialize_row(row: dict) -> dict:
    """Convertit les types non-JSON-sérialisables (Decimal, datetime, date)."""
    import decimal
    from datetime import datetime, date as date_type
    result = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            result[k] = float(v)
        elif isinstance(v, (datetime, date_type)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result
