"""Modelos persistentes exclusivos del dominio DBI."""

from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.assets import AnalysisArtifact, AnalysisInputAsset
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

__all__ = [
    "AnalysisArtifact",
    "AnalysisInputAsset",
    "AnalysisJob",
    "AnalysisJobAttempt",
    "Campaign",
    "DBIMembership",
    "DBIMembershipPermission",
    "DBIMembershipScope",
    "DBIMembershipScopeType",
    "DBIMembershipStatus",
    "DBIPrincipal",
    "DBIPrincipalStatus",
    "Farm",
    "Plot",
]
