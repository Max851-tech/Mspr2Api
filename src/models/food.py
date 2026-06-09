from pydantic import BaseModel, Field
from typing import Optional


class DetectedFood(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    quantity_g: Optional[float] = None


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
