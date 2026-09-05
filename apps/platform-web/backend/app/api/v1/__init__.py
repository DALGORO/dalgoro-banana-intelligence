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
from .dbi_admin import router as dbi_admin_router
from .dbi_admin_principals import router as dbi_admin_principals_router
from .dbi_analysis_jobs import router as dbi_analysis_jobs_router
from .dbi_asset_multipart import router as dbi_asset_multipart_router
from .dbi_assets import router as dbi_assets_router
from .dbi_flight_source_manifests import (
    router as dbi_flight_source_manifests_router,
)
from .dbi_inspection import router as dbi_inspection_router
from .dbi_map import router as dbi_map_router
from .dbi_raster_products import router as dbi_raster_products_router
from .dbi_reads import router as dbi_reads_router
from .dbi_sampling import router as dbi_sampling_router
from .dbi_spatial import router as dbi_spatial_router
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
    api.include_router(dbi_admin_router)
    api.include_router(dbi_admin_principals_router)
    api.include_router(dbi_analysis_jobs_router)
    api.include_router(dbi_assets_router)
    api.include_router(dbi_asset_multipart_router)
    api.include_router(dbi_flight_source_manifests_router)
    api.include_router(dbi_inspection_router)
    api.include_router(dbi_map_router)
    api.include_router(dbi_raster_products_router)
    api.include_router(dbi_reads_router)
    api.include_router(dbi_sampling_router)
    api.include_router(dbi_spatial_router)
    api.include_router(dbi_writes_router)

    if getattr(settings, "ENABLE_DOCS", False):
        api.include_router(documents_router)

    return api
