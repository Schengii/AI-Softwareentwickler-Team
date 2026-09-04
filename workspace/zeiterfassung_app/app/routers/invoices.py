from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..schemas import InvoiceCreate

router = APIRouter()

@router.post("/generate-invoice")
async def generate_invoice(
    data: InvoiceCreate,
    db: AsyncSession = Depends(get_db)
):
    # Hier Logik zur Rechnungsgenerierung
    return {"message": "Rechnung erstellt", "invoice_id": data.invoice_id}
