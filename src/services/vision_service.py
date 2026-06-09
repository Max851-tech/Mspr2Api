"""
Service de reconnaissance visuelle d'aliments.
Priorité : HuggingFace Inference API → Google Vision API → fallback local transformers
"""
import httpx
import base64
import json
import logging
from typing import Optional

from src.config.settings import settings
from src.models.food import DetectedFood

logger = logging.getLogger(__name__)


async def analyze_food_image(image_bytes: bytes) -> tuple[list[DetectedFood], str]:
    """
    Analyse une image et retourne les aliments détectés.
    Retourne (liste d'aliments, source utilisée).
    """
    if settings.HF_API_KEY:
        result = await _analyze_with_huggingface(image_bytes)
        if result:
            return result, "huggingface"

    if settings.GOOGLE_VISION_API_KEY:
        result = await _analyze_with_google_vision(image_bytes)
        if result:
            return result, "google_vision"

    # Fallback : retour générique si aucune API configurée
    logger.warning("Aucune API vision configurée, utilisation du fallback.")
    return _fallback_detection(), "fallback"


async def _analyze_with_huggingface(image_bytes: bytes) -> Optional[list[DetectedFood]]:
    """Appel au modèle de classification alimentaire HuggingFace."""
    url = f"{settings.HF_INFERENCE_URL}/{settings.HF_FOOD_MODEL}"
    headers = {"Authorization": f"Bearer {settings.HF_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, content=image_bytes, headers=headers)
            response.raise_for_status()
            predictions = response.json()

        return [
            DetectedFood(
                name=p["label"].replace("_", " ").lower(),
                confidence=round(p["score"], 3),
            )
            for p in predictions[:5]  # top 5
        ]
    except Exception as e:
        logger.error(f"HuggingFace vision error: {e}")
        return None


async def _analyze_with_google_vision(image_bytes: bytes) -> Optional[list[DetectedFood]]:
    """Appel à l'API Google Cloud Vision pour la détection d'aliments."""
    url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.GOOGLE_VISION_API_KEY}"
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "requests": [{
            "image": {"content": b64_image},
            "features": [
                {"type": "LABEL_DETECTION", "maxResults": 10},
                {"type": "WEB_DETECTION", "maxResults": 5},
            ],
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        labels = data["responses"][0].get("labelAnnotations", [])
        food_keywords = {"food", "dish", "cuisine", "meal", "ingredient", "recipe"}

        foods = []
        for label in labels:
            desc = label["description"].lower()
            score = label["score"]
            # Filtrer uniquement les labels liés à la nourriture
            if score > 0.6 and any(k in desc for k in food_keywords) or score > 0.8:
                foods.append(DetectedFood(name=desc, confidence=round(score, 3)))

        return foods[:5] if foods else None
    except Exception as e:
        logger.error(f"Google Vision error: {e}")
        return None


def _fallback_detection() -> list[DetectedFood]:
    """Retourne un aliment générique quand aucune API n'est disponible."""
    return [DetectedFood(name="plat non identifié", confidence=0.0)]
