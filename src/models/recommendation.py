from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class HealthGoal(str, Enum):
    WEIGHT_LOSS = "weight_loss"
    MUSCLE_GAIN = "muscle_gain"
    ENDURANCE = "endurance"
    GENERAL_HEALTH = "general_health"
    NUTRITIONAL_BALANCE = "nutritional_balance"


class FitnessLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class UserProfile(BaseModel):
    age: int = Field(ge=10, le=100)
    weight_kg: float = Field(ge=30.0, le=300.0)
    height_cm: float = Field(ge=100.0, le=250.0)
    goal: HealthGoal
    fitness_level: FitnessLevel = FitnessLevel.BEGINNER
    allergies: list[str] = []
    dietary_preferences: list[str] = []
    budget_per_day_eur: Optional[float] = None


class NutritionRecommendationRequest(BaseModel):
    profile: UserProfile
    current_macros: Optional[dict] = None  # macros du jour si disponibles


class SportRecommendationRequest(BaseModel):
    profile: UserProfile
    available_equipment: list[str] = []
    session_duration_min: int = Field(default=45, ge=10, le=180)
    sessions_per_week: int = Field(default=3, ge=1, le=7)
    injuries: list[str] = []
    preferred_activities: list[str] = []


class MealPlan(BaseModel):
    day: str
    meals: list[dict]
    total_macros: dict


class ExerciseSession(BaseModel):
    name: str
    duration_min: int
    exercises: list[dict]
    intensity: str


class NutritionRecommendationResponse(BaseModel):
    daily_targets: dict
    meal_plan: list[MealPlan]
    recommendations: list[str]
    model_used: str


class SportRecommendationResponse(BaseModel):
    weekly_program: list[ExerciseSession]
    recommendations: list[str]
    progression_notes: str
    model_used: str
