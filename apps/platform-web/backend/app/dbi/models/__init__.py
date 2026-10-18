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
from app.dbi.models.campaign_artifacts import DBICampaignArtifact
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
from app.dbi.models.inspection_campaign import (
    DBIInspectionApprovalEventRecord,
    DBIInspectionCampaignLinkRecord,
)
from app.dbi.models.inspection_staff import (
    DBIInspectionInstitutionalStaffAuditRecord,
    DBIInspectionInstitutionalStaffRoleRecord,
)
from app.dbi.models.model_registry import (
    DBIAnalysisProfile,
    DBIModelGovernanceEvent,
    DBIModelVersion,
    DBIPipelineConfigVersion,
)
from app.dbi.models.multispectral import DBIMultispectralExtractionRecord
from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.models.portal_vectors import DBIPortalVectorLayer
from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview
from app.dbi.models.sampling import DBISamplingPlanRecord, DBISamplingPointRecord
from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding

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
    "DBICampaignArtifact",
    "DBIDeliveryMessage",
    "DBIFieldObservationRecord",
    "DBIFieldObservationVersionRecord",
    "DBIInspectionApprovalEventRecord",
    "DBIInspectionCampaignLinkRecord",
    "DBIInspectionInstitutionalStaffAuditRecord",
    "DBIInspectionInstitutionalStaffRoleRecord",
    "DBIMembership",
    "DBIMembershipPermission",
    "DBIMembershipScope",
    "DBIMembershipScopeType",
    "DBIMembershipStatus",
    "DBIModelGovernanceEvent",
    "DBIModelVersion",
    "DBIMultispectralExtractionRecord",
    "DBIPipelineConfigVersion",
    "DBIPrincipal",
    "DBIPrincipalStatus",
    "DBIRasterProduct",
    "DBIPortalVectorLayer",
    "DBIPortalGISImport",
    "DBIPortalGISPreview",
    "DBISamplingPlanRecord",
    "DBISamplingPointRecord",
    "DBIScientificRasterBinding",
    "Farm",
    "FlightSourceBundle",
    "FlightSourceEntry",
    "Plot",
]
