from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .models import AsyncSessionLocal, MockDefinition, TrafficLog, init_db
from .schemas import MockCreate, MockResponse, TrafficLogResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="MockForge API", lifespan=lifespan)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/api/v1/mocks", response_model=list[MockResponse])
async def get_mocks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MockDefinition))
    return result.scalars().all()

@app.post("/api/v1/mocks", response_model=MockResponse)
async def create_mock(mock: MockCreate, db: AsyncSession = Depends(get_db)):
    new_mock = MockDefinition(**mock.dict())
    db.add(new_mock)
    await db.commit()
    await db.refresh(new_mock)
    return new_mock

@app.get("/api/v1/logs", response_model=list[TrafficLogResponse])
async def get_logs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrafficLog))
    return result.scalars().all()

@app.get("/")
async def read_index():
    return {"message": "MockForge Backend running. Access dashboard at /static/index.html"}
