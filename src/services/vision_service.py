"""
Service de reconnaissance visuelle d'aliments.
Priorité : Google Gemini Vision → HuggingFace → fallback
"""
import httpx
import base64
import logging
from typing import Optional

from src.config.settings import settings
from src.models.food import DetectedFood

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


async def analyze_food_image(image_bytes: bytes) -> tuple[list[DetectedFood], str]:
    """
    Analyse une image et retourne les aliments détectés.
    Retourne (liste d'aliments, source utilisée).
    """
    if settings.GEMINI_API_KEY:
        result = await _analyze_with_gemini(image_bytes)
        if result:
            return result, "gemini"

    if settings.HF_API_KEY:
        result = await _analyze_with_huggingface(image_bytes)
        if result:
            return result, "huggingface"

    if settings.GOOGLE_VISION_API_KEY:
        result = await _analyze_with_google_vision(image_bytes)
        if result:
            return result, "google_vision"

    logger.warning("Aucune API vision disponible, utilisation du fallback.")
    return _fallback_detection(), "fallback"


async def _analyze_with_gemini(image_bytes: bytes) -> Optional[list[DetectedFood]]:
    """Utilise Gemini 1.5 Flash pour identifier les aliments dans l'image."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [{
            "parts": [
                {
                    "text": (
                        "Identifie tous les aliments visibles dans cette image et estime leurs macronutriments "
                        "pour une portion standard visible. "
                        "Réponds UNIQUEMENT avec une liste JSON de ce format exact (sans markdown, sans texte autour) : "
                        '[{"name": "nom_aliment", "confidence": 0.95, "quantity_g": 150, '
                        '"macros": {"calories": 200, "proteins_g": 25, "carbs_g": 10, "fats_g": 8, "fiber_g": 2}}, ...]. '
                        "Donne les noms en français. Maximum 6 aliments."
                    )
                },
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64,
                    }
                }
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{GEMINI_URL}?key={settings.GEMINI_API_KEY}",
                json=payload,
            )
        logger.info(f"Gemini status: {response.status_code} | body: {response.text[:500]}")
        if response.status_code == 429:
            logger.error(f"Gemini 429 detail: {response.text}")
            return None
        response.raise_for_status()

        import json, re
        data = response.json()
        # Concaténer toutes les parties de la réponse
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        logger.info(f"Gemini raw text: {text[:500]}")

        # Nettoyer les balises markdown
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()

        # Extraire tous les objets JSON complets même si le tableau est tronqué
        foods = re.findall(r'\{[^{}]*"name"[^{}]*"macros"\s*:\s*\{[^{}]*\}[^{}]*\}', text, re.DOTALL)
        if not foods:
            # Fallback : objets sans macros
            foods = re.findall(r'\{[^{}]*"name"\s*:\s*"[^"]*"[^{}]*\}', text)
        if not foods:
            logger.error(f"Gemini: pas de JSON trouvé: {text[:300]}")
            return None

        # Parser chaque objet individuellement
        parsed = []
        for f in foods:
            try:
                parsed.append(json.loads(f))
            except Exception:
                pass
        if not parsed:
            return None
        foods = parsed
        from src.models.food import FoodMacros
        result = []
        for f in foods[:6]:
            macros = None
            if "macros" in f and isinstance(f["macros"], dict):
                macros = FoodMacros(**{k: float(v) for k, v in f["macros"].items()})
            result.append(DetectedFood(
                name=f["name"],
                confidence=round(float(f.get("confidence", 0.9)), 3),
                quantity_g=float(f["quantity_g"]) if f.get("quantity_g") else None,
                macros=macros,
            ))
        return result
    except Exception as e:
        logger.error(f"Gemini vision error: {type(e).__name__}: {e}")
        return None


async def _analyze_with_huggingface(image_bytes: bytes) -> Optional[list[DetectedFood]]:
    """Appel au modèle de classification alimentaire HuggingFace."""
    url = f"{settings.HF_INFERENCE_URL}/{settings.HF_FOOD_MODEL}"
    headers = {
        "Authorization": f"Bearer {settings.HF_API_KEY}",
        "Content-Type": "application/octet-stream",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, content=image_bytes, headers=headers)

        logger.info(f"HuggingFace status: {response.status_code} | body: {response.text[:200]}")

        if response.status_code == 503:
            import asyncio
            await asyncio.sleep(10)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, content=image_bytes, headers=headers)

        response.raise_for_status()
        predictions = response.json()

        if not isinstance(predictions, list):
            return None

        return [
            DetectedFood(
                name=p["label"].replace("_", " ").lower(),
                confidence=round(p["score"], 3),
            )
            for p in predictions[:5]
        ]
    except Exception as e:
        logger.error(f"HuggingFace vision error: {type(e).__name__}: {e}")
        return None


async def _analyze_with_google_vision(image_bytes: bytes) -> Optional[list[DetectedFood]]:
    """Appel à l'API Google Cloud Vision."""
    url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.GOOGLE_VISION_API_KEY}"
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "requests": [{
            "image": {"content": b64_image},
            "features": [{"type": "LABEL_DETECTION", "maxResults": 10}],
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        labels = data["responses"][0].get("labelAnnotations", [])
        foods = [
            DetectedFood(name=l["description"].lower(), confidence=round(l["score"], 3))
            for l in labels if l["score"] > 0.7
        ]
        return foods[:5] if foods else None
    except Exception as e:
        logger.error(f"Google Vision error: {e}")
        return None


def _fallback_detection() -> list[DetectedFood]:
    return [DetectedFood(name="plat non identifié", confidence=0.0)]
