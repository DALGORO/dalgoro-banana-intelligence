"""Proyección pública mínima INSPECT, solo aprobada por Campaign MULTI."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.dbi.inspection.published_read_service import DBIApprovedInspectionSummary


class DBIApprovedInspectionPublicItem(BaseModel):
    """Sin UUID de registros internos, GPS, notas, fotos ni identidad del técnico."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    foure_state: str
    foure_value: int | None
    yls_state: str
    yls_value: int | None
    functional_leaves_state: str
    functional_leaves_value: int | None

    @classmethod
    def from_approved(
        cls, summary: DBIApprovedInspectionSummary,
    ) -> "DBIApprovedInspectionPublicItem":
        return cls(
            observed_at=summary.observed_at,
            foure_state=summary.foure_state,
            foure_value=summary.foure_value,
            yls_state=summary.yls_state,
            yls_value=summary.yls_value,
            functional_leaves_state=summary.functional_leaves_state,
            functional_leaves_value=summary.functional_leaves_value,
        )
