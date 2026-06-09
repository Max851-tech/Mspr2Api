"""Utilitaires de traitement d'images avant envoi aux APIs de vision."""
from PIL import Image
import io

MAX_SIZE = (1024, 1024)
MAX_BYTES = 4 * 1024 * 1024  # 4MB


def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Redimensionne et optimise une image pour les APIs vision.
    Retourne les bytes JPEG optimisés.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail(MAX_SIZE, Image.LANCZOS)

    output = io.BytesIO()
    quality = 85
    img.save(output, format="JPEG", quality=quality, optimize=True)

    # Réduire la qualité si trop volumineux
    while output.tell() > MAX_BYTES and quality > 50:
        output = io.BytesIO()
        quality -= 10
        img.save(output, format="JPEG", quality=quality, optimize=True)

    return output.getvalue()
