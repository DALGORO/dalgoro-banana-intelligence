"""Modelos persistentes exclusivos del dominio DBI."""

from app.dbi.models.admin_audit import (
    DBI_ADMIN_AUDIT_ACTION_VALUES,
    DBI_ADMIN_AUDIT_RESOURCE_VALUES,
    DBIAdminAuditAction,
    DBIAdminAuditEvent,
    DBIAdminAuditOutcome,
    DBIAdminAuditResourceType,
)
from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.analysis_results import DBIAnalysisResult
from app.dbi.models.asset_multipart import AssetMultipartPart, AssetMultipartSession
from app.dbi.models.assets import AnalysisArtifact, AnalysisInputAsset
from app.dbi.models.delivery import DBIDeliveryMessage
from app.dbi.models.flight_source_manifest import FlightSourceBundle, FlightSourceEntry
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)
from app.dbi.models.inspection import (
    DBIFieldObservationRecord,
    DBIFieldObservationVersionRecord,
)
from app.dbi.models.model_registry import (
    DBIAnalysisProfile,
    DBIModelGovernanceEvent,
    DBIModelVersion,
    DBIPipelineConfigVersion,
)
from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.models.sampling import DBISamplingPlanRecord, DBISamplingPointRecord

__all__ = [
    "AnalysisArtifact",
    "AnalysisInputAsset",
    "AnalysisJob",
    "AnalysisJobAttempt",
    "AssetMultipartPart",
    "AssetMultipartSession",
    "Campaign",
    "DBI_ADMIN_AUDIT_ACTION_VALUES",
    "DBI_ADMIN_AUDIT_RESOURCE_VALUES",
    "DBIAdminAuditAction",
    "DBIAdminAuditEvent",
    "DBIAdminAuditOutcome",
    "DBIAdminAuditResourceType",
    "DBIAnalysisProfile",
    "DBIAnalysisResult",
    "DBIDeliveryMessage",
    "DBIFieldObservationRecord",
    "DBIFieldObservationVersionRecord",
    "DBIMembership",
    "DBIMembershipPermission",
    "DBIMembershipScope",
    "DBIMembershipScopeType",
    "DBIMembershipStatus",
    "DBIModelGovernanceEvent",
    "DBIModelVersion",
    "DBIPipelineConfigVersion",
    "DBIPrincipal",
    "DBIPrincipalStatus",
    "DBIRasterProduct",
    "DBISamplingPlanRecord",
    "DBISamplingPointRecord",
    "Farm",
    "FlightSourceBundle",
    "FlightSourceEntry",
    "Plot",
]
