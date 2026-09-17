"""Schemas für Flotten- und Telemetriedaten."""

from enum import Enum

from pydantic import BaseModel, Field


class VehicleType(str, Enum):
    """Fahrzeugtypen der Flotte."""
    DIESEL_VAN = "diesel_van"
    ELECTRIC_VAN = "electric_van"
    HEAVY_TRUCK = "heavy_truck"
    ELECTRIC_TRUCK = "electric_truck"
    HYBRID_CAR = "hybrid_car"
    E_CARGO_BIKE = "e_cargo_bike"


class FleetEmissionsRequest(BaseModel):
    """Anfrageschema für Flotten-Emissionsberechnung."""
    vehicle_type: VehicleType = Field(..., description="Typ des Fahrzeugs")
    distance_km: float = Field(..., gt=0, description="Fahrstrecke in Kilometern")
    cargo_weight_kg: float = Field(default=0.0, ge=0, description="Ladungsgewicht in kg")
    ambient_temp_c: float | None = Field(default=20.0, description="Umgebungstemperatur in Celsius")
    idle_time_min: float | None = Field(default=0.0, ge=0, description="Leerlaufzeit in Minuten")


class FleetEmissionsResponse(BaseModel):
    """Ergebnisschema für Flotten-Emissionsberechnung."""
    vehicle_type: VehicleType
    distance_km: float
    cargo_weight_kg: float
    co2_emissions_kg: float = Field(..., description="Gesamte CO2-Emissionen in kg")
    energy_consumption: float = Field(..., description="Verbrauch in Litern oder kWh")
    energy_unit: str = Field(..., description="'l' für Diesel/Benzin, 'kWh' für Elektro")
    efficiency_score: float = Field(..., ge=0.0, le=100.0, description="Effizienzbewertung von 0 bis 100")
    savings_potential_kg: float = Field(default=0.0, ge=0, description="Einsparpotenzial durch Elektrifizierung/Optimierung")
    recommendations: list[str] = Field(default_factory=list, description="Handlungsempfehlungen zur Reduktion")
