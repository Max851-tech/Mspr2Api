"""Repository pour les analyses de repas (collection 'food_analyses')."""
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.db_documents import FoodAnalysisDocument
from src.core.database import get_db

COLLECTION = "food_analyses"


async def save_analysis(doc: FoodAnalysisDocument) -> str:
    """Persiste une analyse en base. Retourne l'ID MongoDB créé."""
    db: AsyncIOMotorDatabase = get_db()
    result = await db[COLLECTION].insert_one(doc.model_dump())
    return str(result.inserted_id)


async def get_analyses_by_user(user_id: str, limit: int = 20) -> list[dict]:
    """Récupère les dernières analyses d'un utilisateur."""
    db: AsyncIOMotorDatabase = get_db()
    cursor = db[COLLECTION].find(
        {"user_id": user_id},
        sort=[("created_at", -1)],
        limit=limit,
    )
    docs = await cursor.to_list(length=limit)
    return [_serialize(d) for d in docs]


async def get_analyses_by_session(session_id: str, limit: int = 10) -> list[dict]:
    """Récupère les analyses d'une session anonyme."""
    db: AsyncIOMotorDatabase = get_db()
    cursor = db[COLLECTION].find(
        {"session_id": session_id},
        sort=[("created_at", -1)],
        limit=limit,
    )
    docs = await cursor.to_list(length=limit)
    return [_serialize(d) for d in docs]


def _serialize(doc: dict) -> dict:
    """Convertit l'ObjectId MongoDB en string."""
    doc["id"] = str(doc.pop("_id"))
    return doc
