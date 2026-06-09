"""Repository pour les recommandations (collection 'recommendations')."""
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.db_documents import RecommendationDocument
from src.core.database import get_db

COLLECTION = "recommendations"


async def save_recommendation(doc: RecommendationDocument) -> str:
    """Persiste une recommandation. Retourne l'ID MongoDB."""
    db: AsyncIOMotorDatabase = get_db()
    result = await db[COLLECTION].insert_one(doc.model_dump())
    return str(result.inserted_id)


async def get_recommendations_by_user(
    user_id: str,
    rec_type: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Récupère les recommandations d'un utilisateur, filtrées par type si précisé."""
    db: AsyncIOMotorDatabase = get_db()
    query: dict = {"user_id": user_id}
    if rec_type:
        query["type"] = rec_type

    cursor = db[COLLECTION].find(query, sort=[("created_at", -1)], limit=limit)
    docs = await cursor.to_list(length=limit)
    return [_serialize(d) for d in docs]


async def get_latest_recommendation(user_id: str, rec_type: str) -> dict | None:
    """Récupère la dernière recommandation d'un type donné pour un utilisateur."""
    db: AsyncIOMotorDatabase = get_db()
    doc = await db[COLLECTION].find_one(
        {"user_id": user_id, "type": rec_type},
        sort=[("created_at", -1)],
    )
    return _serialize(doc) if doc else None


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc
