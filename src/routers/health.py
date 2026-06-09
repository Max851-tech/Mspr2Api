from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/health", summary="Health check")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "service": "ai-service"}
