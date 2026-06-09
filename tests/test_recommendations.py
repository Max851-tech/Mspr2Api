"""Tests pour le moteur de recommandations nutrition & sport."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.routers.recommendations import detect_imbalances_from_current, _get_intensity, _filter_exercises_for_injuries


# ─── Tests utilitaires ────────────────────────────────────────────────────────

def test_detect_imbalances_from_current_excess():
    current = {"calories": 3000, "proteins_g": 80, "carbs_g": 400, "fats_g": 100}
    targets = {"calories": 2000, "proteins_g": 60, "carbs_g": 260, "fats_g": 65}
    result = detect_imbalances_from_current(current, targets)
    assert any("excès" in i.lower() for i in result)


def test_detect_imbalances_from_current_none():
    result = detect_imbalances_from_current(None, {})
    assert result == []


def test_get_intensity_levels():
    assert _get_intensity("beginner") == "Faible"
    assert _get_intensity("intermediate") == "Modérée"
    assert _get_intensity("advanced") == "Élevée"


def test_filter_exercises_for_injuries():
    exercises = [
        {"name": "Squats", "sets": 3, "reps": 15},
        {"name": "Fentes", "sets": 3, "reps": 12},
        {"name": "Gainage planche", "sets": 3, "reps": None},
    ]
    filtered = _filter_exercises_for_injuries(exercises, ["douleur genou"])
    names = [e["name"].lower() for e in filtered]
    assert "squats" not in names
    assert "gainage planche" in names


# ─── Tests API endpoints ──────────────────────────────────────────────────────

NUTRITION_PAYLOAD = {
    "profile": {
        "age": 28,
        "weight_kg": 70,
        "height_cm": 175,
        "goal": "weight_loss",
        "fitness_level": "intermediate",
        "allergies": ["gluten"],
        "budget_per_day_eur": 15,
    }
}

SPORT_PAYLOAD = {
    "profile": {
        "age": 28,
        "weight_kg": 70,
        "height_cm": 175,
        "goal": "muscle_gain",
        "fitness_level": "intermediate",
    },
    "available_equipment": ["haltères", "barre"],
    "session_duration_min": 60,
    "sessions_per_week": 4,
    "injuries": [],
}


@pytest.fixture
def mock_llm_nutrition():
    with (
        patch(
            "src.routers.recommendations.generate_nutrition_recommendations",
            new_callable=AsyncMock,
            return_value=(["Mangez plus de légumes.", "Réduisez le sucre."], "ollama"),
        ),
        patch(
            "src.routers.recommendations.generate_meal_plan",
            new_callable=AsyncMock,
            return_value=([{"day": "Lundi", "meals": [{"name": "Déjeuner", "description": "Poulet riz"}], "total_macros": {}}], "ollama"),
        ),
    ):
        yield


@pytest.fixture
def mock_llm_sport():
    with patch(
        "src.routers.recommendations.generate_sport_recommendations",
        new_callable=AsyncMock,
        return_value=(["Augmentez les charges progressivement.", "Dormez 8h."], "Augmentez de 5% par semaine.", "ollama"),
    ):
        yield


@pytest.mark.asyncio
async def test_nutrition_recommendations_success(mock_llm_nutrition):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/recommendations/nutrition", json=NUTRITION_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert "daily_targets" in data
    assert "recommendations" in data
    assert data["daily_targets"]["calories"] > 0


@pytest.mark.asyncio
async def test_sport_recommendations_success(mock_llm_sport):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/recommendations/sport", json=SPORT_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert "weekly_program" in data
    assert len(data["weekly_program"]) == 4  # sessions_per_week


@pytest.mark.asyncio
async def test_nutrition_invalid_age(mock_llm_nutrition):
    payload = {**NUTRITION_PAYLOAD, "profile": {**NUTRITION_PAYLOAD["profile"], "age": 5}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/recommendations/nutrition", json=payload)
    assert response.status_code == 422  # Validation Pydantic


@pytest.mark.asyncio
async def test_sport_invalid_sessions(mock_llm_sport):
    payload = {**SPORT_PAYLOAD, "sessions_per_week": 10}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/recommendations/sport", json=payload)
    assert response.status_code == 422
