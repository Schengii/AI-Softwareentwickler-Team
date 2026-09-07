
import os

import joblib
import numpy as np
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.telemetry import Telemetry

app = FastAPI(title="Predictive Maintenance ML Service")

# Pfad zum Modell-Artefakt
MODEL_PATH = "models/maintenance_rf_v1.pkl"

class TelemetryData(BaseModel):
    vehicle_id: str
    sensor_readings: list[float]

class PredictionResponse(BaseModel):
    vehicle_id: str
    maintenance_probability: float
    status: str

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

model = load_model()

def predict_maintenance(data: list[float]) -> float:
    if not data:
        return 0.0
    
    # Falls Modell geladen, nutze es, sonst Fallback auf Heuristik
    if model:
        # Erwartet z.B. ein 2D Array [1, n_features]
        return float(model.predict_proba(np.array(data).reshape(1, -1))[0][1])
    
    return min(max(np.mean(data) / 100.0, 0.0), 1.0)

@app.post("/predict", response_model=PredictionResponse)
async def predict(payload: TelemetryData, db: AsyncSession = Depends(get_db)):
    try:
        prob = predict_maintenance(payload.sensor_readings)
        status = "CRITICAL" if prob > 0.8 else "WARNING" if prob > 0.5 else "HEALTHY"
        
        # Persistenz: Speichere Ergebnis in der DB
        new_telemetry = Telemetry(
            vehicle_id=int(payload.vehicle_id), # Annahme: ID ist numerisch
            diagnostics={"prob": prob, "status": status}
        )
        db.add(new_telemetry)
        await db.commit()
        
        return {
            "vehicle_id": payload.vehicle_id,
            "maintenance_probability": float(prob),
            "status": status
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
