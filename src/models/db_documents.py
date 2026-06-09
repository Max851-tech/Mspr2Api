"""
Documents MongoDB stockés par l'ai-service.

Collections :
  - food_analyses     → historique des analyses de repas
  - recommendations   → recommandations nutrition/sport générées
  - user_profiles_ai  → cache des profils utilisateurs (depuis backend ou saisis)
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class FoodAnalysisDocument(BaseModel):
    """Stocké dans la collection 'food_analyses'."""
    user_id: Optional[str] = None       # ID utilisateur du backend TPRE501
    session_id: str                      # UUID de la session si non connecté
    detected_foods: list[dict]
    total_macros: dict
    imbalances: list[str]
    suggestions: list[str]
    analysis_source: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecommendationDocument(BaseModel):
    """Stocké dans la collection 'recommendations'."""
    user_id: Optional[str] = None
    session_id: str
    type: str                            # "nutrition" | "sport"
    profile_snapshot: dict               # copie du profil au moment de la génération
    daily_targets: Optional[dict] = None
    meal_plan: Optional[list] = None
    weekly_program: Optional[list] = None
    recommendations: list[str]
    model_used: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserProfileCacheDocument(BaseModel):
    """
    Stocké dans la collection 'user_profiles_ai'.
    Cache du profil utilisateur enrichi par les préférences IA.
    Synchronisé depuis le backend TPRE501 si connecté.
    """
    user_id: str                         # ID du backend TPRE501
    age: int
    weight_kg: float
    height_cm: float
    goal: str
    fitness_level: str
    allergies: list[str] = []
    dietary_preferences: list[str] = []
    budget_per_day_eur: Optional[float] = None
    injuries: list[str] = []
    last_synced_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
