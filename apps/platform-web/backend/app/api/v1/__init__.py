from fastapi import APIRouter
from app.core.config import settings

from .routes_health import router as health_router
from .auth import router as auth_router
from .users import router as users_router
from .companies import router as companies_router
from .documents import router as documents_router
from .files import router as files_router
from .subscriptions import router as subscriptions_router
from .templates import router as templates_router
from .system import router as system_router
from .iperc import router as iperc_router
from .psico import router as psico_router
from .incident_assistant import router as incident_assistant_router
from .dbi_map import router as dbi_map_router
from .dbi_reads import router as dbi_reads_router
from .dbi_writes import router as dbi_writes_router


def get_api_router() -> APIRouter:
    api = APIRouter()
    api.include_router(health_router)
    api.include_router(auth_router)
    api.include_router(users_router)
    api.include_router(companies_router)
    api.include_router(files_router)
    api.include_router(subscriptions_router)
    api.include_router(templates_router)
    api.include_router(system_router)
    api.include_router(iperc_router)
    api.include_router(psico_router)
    api.include_router(incident_assistant_router)
    api.include_router(dbi_map_router)
    api.include_router(dbi_reads_router)
    api.include_router(dbi_writes_router)

    if getattr(settings, "ENABLE_DOCS", False):
        api.include_router(documents_router)

    return api
