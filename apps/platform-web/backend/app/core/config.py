from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# 1) Localiza .env de forma ABSOLUTA (independiente del cwd)
#    .../backend/app/core/config.py -> parents[3] -> .../sst-compliance/.env
ENV_CANDIDATES = [
    Path(__file__).resolve().parents[3] / ".env",  # repo root
    Path(__file__).resolve().parents[2] / ".env",  # backend/.env (por si acaso)
]

ENV_PATH = next((p for p in ENV_CANDIDATES if p.exists()), None)
if ENV_PATH:
    load_dotenv(dotenv_path=str(ENV_PATH), override=False)

class Settings(BaseSettings):
    # Proyecto / DB
    PROJECT_NAME: str = "SST Compliance"
    DATABASE_URL: str = Field(..., env="DATABASE_URL")

    # Storage / GCS  (⚠️ dejar solo UNA definición de GCS_BUCKET)
    GCS_BUCKET: str = Field("", env="GCS_BUCKET")
    GCS_CREDENTIALS_JSON: str = Field("", env="GCS_CREDENTIALS_JSON")
    GCS_SIGNED_URL_EXPIRATION_HOURS: int = Field(24, env="GCS_SIGNED_URL_EXPIRATION_HOURS")

    # JWT
    JWT_SECRET: str = Field(..., env="JWT_SECRET")
    JWT_ALGORITHM: str = Field("HS256", env="JWT_ALGORITHM")
    JWT_EXPIRE_MINUTES: int = Field(60, env="JWT_EXPIRE_MINUTES")

    # Payments
    PAYMENT_PROVIDER: Literal["KUSHKI", "DATAFAST", "STRIPE"] = Field("KUSHKI", env="PAYMENT_PROVIDER")
    PAYMENT_CURRENCY: str = Field("USD", env="PAYMENT_CURRENCY")
    WEBHOOK_SECRET: str = Field("", env="WEBHOOK_SECRET")
    
    # === NUEVO: feature flags / docs ===
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "0") == "1"
    DRIVE_WEBAPP_URL: str | None = os.getenv("DRIVE_WEBAPP_URL")
    COMPANY_DOCS_BUCKET: str | None = os.getenv("COMPANY_DOCS_BUCKET")

    # Pydantic v2 config — forzamos a usar la ruta efectiva encontrada
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH else None,
        extra="ignore",
    )

settings = Settings()
