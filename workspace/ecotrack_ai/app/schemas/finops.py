"""Schemas für FinOps-Kostenrechnung und TCO-Analysen."""


from pydantic import BaseModel, Field


class FinOpsCostRequest(BaseModel):
    """Anfrage für FinOps-Kostenberechnung."""
    total_co2_kg: float = Field(..., ge=0, description="Gesamtemissionen der Flotte in kg")
    fuel_spent_eur: float = Field(..., ge=0, description="Treibstoffkosten in EUR")
    electricity_spent_eur: float | None = Field(default=0.0, ge=0, description="Stromkosten in EUR")
    vehicle_count: int = Field(default=1, gt=0, description="Anzahl der Fahrzeuge")
    fleet_distance_km: float | None = Field(default=0.0, ge=0, description="Gesamtlaufleistung der Flotte")


class FinOpsCostResponse(BaseModel):
    """Ergebnis der FinOps-Kostenberechnung."""
    carbon_certificate_cost_eur: float = Field(..., description="Geschätzte Kosten für CO2-Zertifikate")
    tco_current_eur: float = Field(..., description="Aktuelle Gesamtbetriebskosten (TCO)")
    potential_annual_savings_eur: float = Field(..., description="Mögliche jährliche Ersparnis")
    electrification_roi_years: float = Field(..., description="Amortisationsdauer Elektrifizierung in Jahren")
    cost_per_km_eur: float = Field(..., description="Kosten pro Kilometer")
    financial_recommendations: list[str] = Field(default_factory=list, description="FinOps-Empfehlungen")
