"""Tests pour le router d'analyse de repas et les services associés."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.models.food import DetectedFood, Macros
from src.services.nutrition_service import detect_imbalances, calculate_daily_targets, get_macros_for_foods


# ─── Tests nutrition_service ─────────────────────────────────────────────────

def test_calculate_daily_targets_weight_loss():
    targets = calculate_daily_targets(70, "weight_loss", "beginner")
    assert targets["calories"] < calculate_daily_targets(70, "muscle_gain", "beginner")["calories"]
    assert "proteins_g" in targets
    assert "carbs_g" in targets
    assert "fats_g" in targets


def test_calculate_daily_targets_muscle_gain():
    targets = calculate_daily_targets(80, "muscle_gain", "intermediate")
    assert targets["proteins_g"] >= 100  # 1.6g * 80kg = 128g


def test_detect_imbalances_high_fat():
    macros = Macros(calories=900, proteins_g=10, carbs_g=30, fats_g=60, fiber_g=1)
    imbalances = detect_imbalances(macros)
    assert any("graisses" in i.lower() for i in imbalances)


def test_detect_imbalances_low_fiber():
    macros = Macros(calories=400, proteins_g=20, carbs_g=50, fats_g=10, fiber_g=1)
    imbalances = detect_imbalances(macros)
    assert any("fibres" in i.lower() for i in imbalances)


def test_detect_imbalances_balanced():
    macros = Macros(calories=600, proteins_g=25, carbs_g=70, fats_g=18, fiber_g=8)
    imbalances = detect_imbalances(macros)
    assert len(imbalances) == 0


@pytest.mark.asyncio
async def test_get_macros_for_foods_fallback():
    foods = [DetectedFood(name="pizza", confidence=0.9, quantity_g=200)]
    with patch("src.services.nutrition_service._fetch_nutrition", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"calories": 266, "proteins_g": 11, "carbs_g": 33, "fats_g": 10, "fiber_g": 2.3}
        macros = await get_macros_for_foods(foods)
    assert macros.calories == pytest.approx(532.0, 0.1)
    assert macros.proteins_g == pytest.approx(22.0, 0.1)


# ─── Tests API endpoints ──────────────────────────────────────────────────────

@pytest.fixture
def mock_vision():
    with patch(
        "src.routers.food_analysis.analyze_food_image",
        new_callable=AsyncMock,
        return_value=([DetectedFood(name="pizza", confidence=0.92)], "huggingface"),
    ):
        yield


@pytest.fixture
def mock_llm():
    with patch(
        "src.routers.food_analysis.generate_nutrition_recommendations",
        new_callable=AsyncMock,
        return_value=(["Réduisez les graisses saturées.", "Ajoutez des légumes verts."], "ollama"),
    ):
        yield


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_analyze_invalid_file_type(mock_vision, mock_llm):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
        )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_analyze_empty_file(mock_vision, mock_llm):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", b"", "image/jpeg")},
        )
    assert response.status_code == 400
