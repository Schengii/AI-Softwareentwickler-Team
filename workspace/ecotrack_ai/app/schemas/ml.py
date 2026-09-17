"""Schemas für Machine-Learning-Prognosen."""


from pydantic import BaseModel, Field

from app.schemas.fleet import VehicleType


class PredictionRequest(BaseModel):
    """Anfrage für ML-basierte Emissions- und Routenprognose."""
    vehicle_type: VehicleType = Field(..., description="Typ des Fahrzeugs")
    distance_km: float = Field(..., gt=0, description="Distanz in Kilometern")
    cargo_weight_kg: float = Field(default=0.0, ge=0, description="Gewicht der Zuladung in kg")
    route_elevation_gain_m: float | None = Field(default=0.0, ge=0, description="Höhenmeter der Route in Metern")
    traffic_congestion_factor: float | None = Field(default=1.0, ge=1.0, le=3.0, description="Verkehrsfaktor (1.0 = fließend, 2.0+ = Stau)")


class PredictionResponse(BaseModel):
    """Antwort der ML-Prognose."""
    vehicle_type: VehicleType
    distance_km: float
    predicted_co2_kg: float = Field(..., description="Prognostizierte CO2-Emission in kg")
    confidence_interval: tuple[float, float] = Field(..., description="Konfidenzintervall (Min, Max) in kg CO2")
    model_used: str = Field(..., description="Verwendetes Inferenzmodell")
    optimization_insights: list[str] = Field(default_factory=list, description="ML-generierte Optimierungshinweise")
