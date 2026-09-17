"""EcoTrack AI - Flotten-API Router."""

from fastapi import APIRouter, status

from app.schemas.fleet import FleetEmissionsRequest, FleetEmissionsResponse, VehicleType

fleet_router = APIRouter()


@fleet_router.post(
    "/calculate",
    response_model=FleetEmissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Berechnet CO2-Emissionen und Verbrauch für Flottenfahrten",
)
async def calculate_fleet_emissions(payload: FleetEmissionsRequest) -> FleetEmissionsResponse:
    """Berechnet CO2-Emissionen, Energieverbrauch und Einsparpotenzial basierend auf Fahrzeugtyp und Telemetriedaten."""
    weight_factor = 1.0 + (payload.cargo_weight_kg / 2000.0) * 0.2
    idle_extra_l = (payload.idle_time_min or 0.0) * (0.8 / 60.0)  # ~0.8 l pro Stunde Leerlauf
    temp_penalty = 1.0 + (max(0.0, 10.0 - (payload.ambient_temp_c or 20.0)) * 0.01)

    rec = []
    if payload.vehicle_type == VehicleType.DIESEL_VAN:
        consumption = ((payload.distance_km * 0.085 * weight_factor) + idle_extra_l) * temp_penalty
        unit = "l"
        co2 = consumption * 2.68
        score = max(30.0, min(80.0, 100.0 - (co2 / max(payload.distance_km, 1.0)) * 150))
        savings = co2 * 0.65
        rec.append("Umstieg auf Electric Van spart bis zu 65% CO2.")
    elif payload.vehicle_type == VehicleType.ELECTRIC_VAN:
        consumption = (payload.distance_km * 0.24 * weight_factor) * temp_penalty
        unit = "kWh"
        co2 = consumption * 0.38
        score = 88.0
        savings = 0.0
        rec.append("Ökostrom-Ladeinfrastruktur nutzen für vollständige Dekarbonisierung.")
    elif payload.vehicle_type == VehicleType.HEAVY_TRUCK:
        consumption = ((payload.distance_km * 0.32 * weight_factor) + (idle_extra_l * 2.5)) * temp_penalty
        unit = "l"
        co2 = consumption * 2.68
        score = 45.0
        savings = co2 * 0.50
        rec.append("Routen- und Ladebündelung durchführen.")
    elif payload.vehicle_type == VehicleType.ELECTRIC_TRUCK:
        consumption = (payload.distance_km * 1.15 * weight_factor) * temp_penalty
        unit = "kWh"
        co2 = consumption * 0.38
        score = 92.0
        savings = 0.0
        rec.append("Batterievorkonditionierung im Depot aktivieren.")
    elif payload.vehicle_type == VehicleType.HYBRID_CAR:
        consumption = (payload.distance_km * 0.045 * weight_factor) * temp_penalty
        unit = "l"
        co2 = consumption * 2.35
        score = 72.0
        savings = co2 * 0.30
        rec.append("Elektrischen Fahranteil im Stadtgebiet maximieren.")
    else:  # E_CARGO_BIKE
        consumption = payload.distance_km * 0.03
        unit = "kWh"
        co2 = consumption * 0.38
        score = 99.0
        savings = 0.0
        rec.append("Optimale Wahl für urbane Letzte-Meile-Logistik.")

    if (payload.idle_time_min or 0.0) > 15.0:
        rec.append("Leerlaufzeiten reduzieren - Motorabschaltautomatik aktivieren.")

    return FleetEmissionsResponse(
        vehicle_type=payload.vehicle_type,
        distance_km=payload.distance_km,
        cargo_weight_kg=payload.cargo_weight_kg,
        co2_emissions_kg=round(co2, 2),
        energy_consumption=round(consumption, 2),
        energy_unit=unit,
        efficiency_score=round(score, 1),
        savings_potential_kg=round(savings, 2),
        recommendations=rec,
    )
