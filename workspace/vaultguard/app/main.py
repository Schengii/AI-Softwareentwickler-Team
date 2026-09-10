from fastapi import FastAPI
from app.api.routes import router # Annahme: Routen liegen hier

app = FastAPI()
app.include_router(router)
