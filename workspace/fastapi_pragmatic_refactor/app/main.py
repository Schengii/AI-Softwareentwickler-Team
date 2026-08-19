from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db

app = FastAPI()

@app.get("/items")
async def read_items(db: AsyncSession = Depends(get_db)):
    # Direkter Zugriff auf DB-Modelle via Session
    return await db.execute(...)
