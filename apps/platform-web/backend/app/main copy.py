from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import get_api_router
from app.core.config import settings

app = FastAPI(title="SST Compliance API")

# Monta TODA la API v1; psico viene desde app/api/v1/__init__.py
app.include_router(get_api_router(), prefix="/api/v1")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "API SST-Compliance funcionando correctamente 🚀"}
