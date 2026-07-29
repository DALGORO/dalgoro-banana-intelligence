"""Modelos persistentes exclusivos del dominio DBI."""

from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.assets import AnalysisArtifact, AnalysisInputAsset

__all__ = [
    "AnalysisArtifact",
    "AnalysisInputAsset",
    "AnalysisJob",
    "AnalysisJobAttempt",
    "Campaign",
    "Farm",
    "Plot",
]
