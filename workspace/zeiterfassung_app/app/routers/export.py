import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db

router = APIRouter()

@router.get("/time-entries")
async def export_time_entries(
    format: str = "csv",
    db: AsyncSession = Depends(get_db)
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Nur CSV-Export unterstützt")
    
    # In einer echten Anwendung würden wir hier filtern und PII maskieren
    # Die PII-Maskierung erfolgt über die Middleware, wir stellen sicher, dass keine sensiblen Daten unnötig geladen werden
    
    # Beispiel: Abfrage der Daten
    # entries = await db.execute(...)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "ProjectID", "Duration", "IsBilled"])
    # writer.writerows(...)
    
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=export.csv"}
    )
