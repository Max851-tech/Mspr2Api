from pydantic import BaseModel, Field
from typing import Optional


class FoodMacros(BaseModel):
    calories: float = 0.0
    proteins_g: float = 0.0
    carbs_g: float = 0.0
    fats_g: float = 0.0
    fiber_g: float = 0.0


class DetectedFood(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    quantity_g: Optional[float] = None
    macros: Optional[FoodMacros] = None


class Macros(BaseModel):
    calories: float
    proteins_g: float
    carbs_g: float
    fats_g: float
    fiber_g: float = 0.0


class FoodAnalysisResponse(BaseModel):
    detected_foods: list[DetectedFood]
    total_macros: Macros
    imbalances: list[str]
    suggestions: list[str]
    analysis_source: str  # "huggingface" | "google_vision"
