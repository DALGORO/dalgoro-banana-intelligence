"""Modelos persistentes exclusivos del dominio DBI."""

from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt

__all__ = [
    "AnalysisJob",
    "AnalysisJobAttempt",
    "Campaign",
    "Farm",
    "Plot",
]
