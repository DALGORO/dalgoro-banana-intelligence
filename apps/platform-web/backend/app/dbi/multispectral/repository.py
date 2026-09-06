"""Persistencia idempotente de evidencia MULTI derivada y trazable."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.inspection.repository import DBIInspectionConflict
from app.dbi.models.inspection import (
    DBIFieldObservationRecord,
    DBIFieldObservationVersionRecord,
)
from app.dbi.models.multispectral import DBIMultispectralExtractionRecord
from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.multispectral.contracts import (
    DBIMultispectralExtractionCandidate,
    multispectral_extraction_id,
)


class DBIMultispectralPersistenceConflict(ValueError):
    """La derivación MULTI viola scope, provenance o identidad persistida."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DBIMultispectralExtractionRepository:
    """Inserta snapshots derivados; no realiza commit/rollback ni overwrite propios."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIMultispectralPersistenceConflict("session debe ser Session.")
        self._session = session

    @staticmethod
    def _payload_json(candidate: DBIMultispectralExtractionCandidate) -> str:
        return canonical_json(candidate.model_dump(mode="json"))

    def _resolve_observation(
        self,
        candidate: DBIMultispectralExtractionCandidate,
    ) -> tuple[DBIFieldObservationRecord, DBIFieldObservationVersionRecord]:
        result = self._session.execute(
            select(DBIFieldObservationRecord, DBIFieldObservationVersionRecord)
            .join(
                DBIFieldObservationVersionRecord,
                DBIFieldObservationVersionRecord.observation_id
                == DBIFieldObservationRecord.id,
            )
            .where(
                DBIFieldObservationVersionRecord.id == candidate.observation_version_id,
                DBIFieldObservationRecord.tenant_ref == candidate.tenant_ref,
                DBIFieldObservationRecord.organization_ref == candidate.organization_ref,
                DBIFieldObservationRecord.farm_id == candidate.farm_id,
                DBIFieldObservationRecord.plot_id == candidate.plot_id,
            )
        ).one_or_none()
        if result is None:
            raise DBIMultispectralPersistenceConflict(
                "observation_version_id no pertenece al scope DBI autorizado."
            )
        observation, version = result
        if version.evidence_kind != "observed":
            raise DBIMultispectralPersistenceConflict(
                "MULTI sólo puede vincularse a una versión INSPECT observada."
            )
        if (
            version.sampling_point_id != candidate.sampling_point_id
            or version.up_id != candidate.up_id
        ):
            raise DBIMultispectralPersistenceConflict(
                "Sampling/UP deben coincidir exactamente con la versión INSPECT."
            )
        return observation, version

    def _resolve_scientific_raster(
        self,
        candidate: DBIMultispectralExtractionCandidate,
    ) -> DBIRasterProduct:
        raster = self._session.execute(
            select(DBIRasterProduct).where(
                DBIRasterProduct.id == candidate.source_raster_product_id,
                DBIRasterProduct.tenant_ref == candidate.tenant_ref,
                DBIRasterProduct.farm_id == candidate.farm_id,
                DBIRasterProduct.plot_id == candidate.plot_id,
                DBIRasterProduct.product_kind == "scientific",
                DBIRasterProduct.status == "ready",
            )
        ).scalar_one_or_none()
        if raster is None:
            raise DBIMultispectralPersistenceConflict(
                "source_raster_product_id no es un ráster científico ready del scope."
            )
        return raster

    def persist(
        self,
        candidate: DBIMultispectralExtractionCandidate,
    ) -> tuple[DBIMultispectralExtractionRecord, bool]:
        if not isinstance(candidate, DBIMultispectralExtractionCandidate):
            candidate = DBIMultispectralExtractionCandidate.model_validate(candidate)

        observation, _version = self._resolve_observation(candidate)
        self._resolve_scientific_raster(candidate)
        extraction_id = multispectral_extraction_id(candidate)
        payload_json = self._payload_json(candidate)
        payload_sha256 = sha256_text(payload_json)

        inserted = self._session.execute(
            postgresql_insert(DBIMultispectralExtractionRecord)
            .values(
                id=extraction_id,
                tenant_ref=candidate.tenant_ref,
                organization_ref=candidate.organization_ref,
                farm_id=candidate.farm_id,
                plot_id=candidate.plot_id,
                observation_id=observation.id,
                observation_version_id=candidate.observation_version_id,
                source_raster_product_id=candidate.source_raster_product_id,
                sampling_point_id=candidate.sampling_point_id,
                up_id=candidate.up_id,
                schema_version=candidate.schema_version,
                support_mode=candidate.support_mode,
                support_profile_version=candidate.support_profile_version,
                support_limitation=candidate.support_limitation,
                stack_fingerprint=candidate.stack_fingerprint,
                selected_count=candidate.selected_count,
                evidence_kind=candidate.evidence_kind,
                payload_json=payload_json,
                payload_sha256=payload_sha256,
            )
            .on_conflict_do_nothing()
            .returning(DBIMultispectralExtractionRecord.id)
        ).scalar_one_or_none()

        rows = self._session.execute(
            select(DBIMultispectralExtractionRecord).where(
                or_(
                    DBIMultispectralExtractionRecord.id == extraction_id,
                    and_(
                        DBIMultispectralExtractionRecord.observation_version_id
                        == candidate.observation_version_id,
                        DBIMultispectralExtractionRecord.source_raster_product_id
                        == candidate.source_raster_product_id,
                        DBIMultispectralExtractionRecord.support_mode
                        == candidate.support_mode,
                        DBIMultispectralExtractionRecord.support_profile_version
                        == candidate.support_profile_version,
                        DBIMultispectralExtractionRecord.stack_fingerprint
                        == candidate.stack_fingerprint,
                    ),
                )
            )
        ).scalars().all()
        if len(rows) != 1:
            raise DBIMultispectralPersistenceConflict(
                "La identidad MULTI colisiona con más de una extracción persistida."
            )
        row = rows[0]
        exact = (
            row.id == extraction_id
            and row.tenant_ref == candidate.tenant_ref
            and row.organization_ref == candidate.organization_ref
            and row.farm_id == candidate.farm_id
            and row.plot_id == candidate.plot_id
            and row.observation_id == observation.id
            and row.observation_version_id == candidate.observation_version_id
            and row.source_raster_product_id == candidate.source_raster_product_id
            and row.sampling_point_id == candidate.sampling_point_id
            and row.up_id == candidate.up_id
            and row.schema_version == candidate.schema_version
            and row.support_mode == candidate.support_mode
            and row.support_profile_version == candidate.support_profile_version
            and row.support_limitation == candidate.support_limitation
            and row.stack_fingerprint == candidate.stack_fingerprint
            and row.selected_count == candidate.selected_count
            and row.evidence_kind == "derived"
            and row.payload_json == payload_json
            and row.payload_sha256 == payload_sha256
        )
        if not exact:
            raise DBIMultispectralPersistenceConflict(
                "La identidad MULTI ya representa un payload derivado divergente."
            )
        if inserted is not None and inserted != row.id:
            raise DBIMultispectralPersistenceConflict(
                "La identidad insertada de la extracción MULTI diverge."
            )
        return row, inserted is not None

    def get_scoped(
        self,
        *,
        extraction_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIMultispectralExtractionRecord | None:
        return self._session.execute(
            select(DBIMultispectralExtractionRecord).where(
                DBIMultispectralExtractionRecord.id == extraction_id,
                DBIMultispectralExtractionRecord.tenant_ref == tenant_ref,
                DBIMultispectralExtractionRecord.farm_id == farm_id,
                DBIMultispectralExtractionRecord.plot_id == plot_id,
            )
        ).scalar_one_or_none()
