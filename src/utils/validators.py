"""Validateurs d'entrée pour les uploads de fichiers."""
from fastapi import HTTPException, UploadFile

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


async def validate_image(file: UploadFile) -> bytes:
    """Valide et lit le fichier image uploadé."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Format non supporté. Formats acceptés : {', '.join(ALLOWED_CONTENT_TYPES)}",
        )

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 10MB)")

    if len(content) < 100:
        raise HTTPException(status_code=400, detail="Fichier image invalide ou vide")

    return content
