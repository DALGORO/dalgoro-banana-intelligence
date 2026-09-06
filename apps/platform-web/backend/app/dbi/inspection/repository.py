"""Repositorio append-only para verdad-terreno de campo DBI."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.inspection.contracts import (
    DBI_FIELD_OBSERVATION_SCHEMA_VERSION,
    DBIFieldObservationCorrection,
    DBIFieldObservationCreate,
    DBIFieldObservationPayload,
    DBIFieldObservationVersion,
)
from app.dbi.models.inspection import (
    DBIFieldObservationRecord,
    DBIFieldObservationVersionRecord,
)
from app.dbi.models.sampling import DBISamplingPlanRecord, DBISamplingPointRecord
from app.dbi.spatial import DBI_SPATIAL_SRID


class DBIInspectionConflict(ValueError):
    """La operación viola identidad, alcance o versionado de INSPECT."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_canonical_actor(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "*" in value
        or len(value) > 128
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DBIInspectionConflict("recorded_by_ref debe ser canónico.")
    return value


class DBIFieldObservationRepository:
    """Persiste nuevas versiones sin commit/rollback ni overwrite propios."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIInspectionConflict("session debe ser Session.")
        self._session = session

    def flush(self) -> None:
        self._session.flush()

    def _validate_sampling_point_scope(self, payload: DBIFieldObservationPayload) -> None:
        if payload.sampling_point_id is None:
            return
        point = self._session.execute(
            select(DBISamplingPointRecord.id)
            .join(
                DBISamplingPlanRecord,
                DBISamplingPlanRecord.id == DBISamplingPointRecord.plan_id,
            )
            .where(
                DBISamplingPointRecord.id == payload.sampling_point_id,
                DBISamplingPlanRecord.tenant_ref == payload.tenant_ref,
                DBISamplingPlanRecord.organization_ref == payload.organization_ref,
                DBISamplingPlanRecord.farm_id == payload.farm_id,
                DBISamplingPlanRecord.plot_id == payload.plot_id,
                DBISamplingPlanRecord.status != "retired",
            )
        ).scalar_one_or_none()
        if point is None:
            raise DBIInspectionConflict(
                "sampling_point_id no pertenece al tenant/finca/lote autorizado."
            )

    @staticmethod
    def _scope_matches(
        record: DBIFieldObservationRecord,
        payload: DBIFieldObservationPayload,
    ) -> bool:
        return (
            record.tenant_ref == payload.tenant_ref
            and record.organization_ref == payload.organization_ref
            and record.farm_id == payload.farm_id
            and record.plot_id == payload.plot_id
        )

    @staticmethod
    def _payload_json(payload: DBIFieldObservationPayload) -> str:
        return canonical_json(payload.model_dump(mode="json"))

    def _new_version_record(
        self,
        *,
        observation_id: UUID,
        version_id: UUID,
        version: int,
        supersedes_version_id: UUID | None,
        correction_reason: str | None,
        payload: DBIFieldObservationPayload,
        recorded_by_ref: str,
    ) -> DBIFieldObservationVersionRecord:
        payload_json = self._payload_json(payload)
        gps = payload.gps_fix
        return DBIFieldObservationVersionRecord(
            id=version_id,
            observation_id=observation_id,
            version=version,
            supersedes_version_id=supersedes_version_id,
            schema_version=DBI_FIELD_OBSERVATION_SCHEMA_VERSION,
            payload_json=payload_json,
            payload_sha256=sha256_text(payload_json),
            operator_ref=payload.operator_ref,
            observed_at=payload.observed_at,
            gps_point=(
                from_shape(
                    Point(gps.longitude, gps.latitude),
                    srid=DBI_SPATIAL_SRID,
                    extended=True,
                )
                if gps is not None
                else None
            ),
            gps_accuracy_m=gps.accuracy_m if gps is not None else None,
            gps_captured_at=gps.captured_at if gps is not None else None,
            sampling_point_id=payload.sampling_point_id,
            up_id=payload.up_id,
            evidence_kind=payload.evidence_kind,
            correction_reason=correction_reason,
            recorded_by_ref=recorded_by_ref,
        )

    def _to_contract(
        self,
        row: DBIFieldObservationVersionRecord,
    ) -> DBIFieldObservationVersion:
        if sha256_text(row.payload_json) != row.payload_sha256:
            raise DBIInspectionConflict("El payload persistido no coincide con su SHA-256.")
        payload = DBIFieldObservationPayload.model_validate_json(row.payload_json)
        if (
            row.schema_version != DBI_FIELD_OBSERVATION_SCHEMA_VERSION
            or row.operator_ref != payload.operator_ref
            or row.observed_at != payload.observed_at
            or row.sampling_point_id != payload.sampling_point_id
            or row.up_id != payload.up_id
            or row.evidence_kind != payload.evidence_kind
        ):
            raise DBIInspectionConflict("La proyección persistida diverge del payload observado.")
        if payload.gps_fix is None:
            if (
                row.gps_point is not None
                or row.gps_accuracy_m is not None
                or row.gps_captured_at is not None
            ):
                raise DBIInspectionConflict("La proyección GPS diverge del payload observado.")
        else:
            if (
                row.gps_point is None
                or row.gps_accuracy_m is None
                or row.gps_captured_at is None
            ):
                raise DBIInspectionConflict("La proyección GPS está incompleta.")
            point = to_shape(row.gps_point)
            if (
                point.geom_type != "Point"
                or round(float(point.x), 7) != round(payload.gps_fix.longitude, 7)
                or round(float(point.y), 7) != round(payload.gps_fix.latitude, 7)
                or float(row.gps_accuracy_m) != payload.gps_fix.accuracy_m
                or row.gps_captured_at != payload.gps_fix.captured_at
            ):
                raise DBIInspectionConflict("La geometría GPS diverge del payload observado.")
        return DBIFieldObservationVersion(
            observation_id=row.observation_id,
            version_id=row.id,
            version=row.version,
            supersedes_version_id=row.supersedes_version_id,
            correction_reason=row.correction_reason,
            created_at=row.created_at,
            payload=payload,
        )

    def create_observation(
        self,
        request: DBIFieldObservationCreate,
        *,
        recorded_by_ref: str,
        observation_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> DBIFieldObservationVersion:
        if not isinstance(request, DBIFieldObservationCreate):
            request = DBIFieldObservationCreate.model_validate(request)
        actor = _require_canonical_actor(recorded_by_ref)
        payload = request.payload
        self._validate_sampling_point_scope(payload)

        observation_id = observation_id or uuid4()
        version_id = version_id or uuid4()
        if self._session.get(DBIFieldObservationRecord, observation_id) is not None:
            raise DBIInspectionConflict("observation_id ya existe.")
        if self._session.get(DBIFieldObservationVersionRecord, version_id) is not None:
            raise DBIInspectionConflict("version_id ya existe.")

        observation = DBIFieldObservationRecord(
            id=observation_id,
            tenant_ref=payload.tenant_ref,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            created_by_ref=actor,
        )
        version = self._new_version_record(
            observation_id=observation_id,
            version_id=version_id,
            version=1,
            supersedes_version_id=None,
            correction_reason=None,
            payload=payload,
            recorded_by_ref=actor,
        )
        self._session.add(observation)
        self._session.add(version)
        self._session.flush()
        return self._to_contract(version)

    def correct_observation(
        self,
        request: DBIFieldObservationCorrection,
        *,
        recorded_by_ref: str,
        version_id: UUID | None = None,
    ) -> DBIFieldObservationVersion:
        if not isinstance(request, DBIFieldObservationCorrection):
            request = DBIFieldObservationCorrection.model_validate(request)
        actor = _require_canonical_actor(recorded_by_ref)
        payload = request.payload

        base = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .join(
                DBIFieldObservationRecord,
                DBIFieldObservationRecord.id
                == DBIFieldObservationVersionRecord.observation_id,
            )
            .where(
                DBIFieldObservationVersionRecord.id == request.base_version_id,
                DBIFieldObservationRecord.tenant_ref == payload.tenant_ref,
                DBIFieldObservationRecord.organization_ref == payload.organization_ref,
                DBIFieldObservationRecord.farm_id == payload.farm_id,
                DBIFieldObservationRecord.plot_id == payload.plot_id,
            )
        ).scalar_one_or_none()
        if base is None:
            raise DBIInspectionConflict(
                "La versión base no pertenece al tenant/finca/lote autorizado."
            )

        observation = self._session.execute(
            select(DBIFieldObservationRecord)
            .where(DBIFieldObservationRecord.id == base.observation_id)
            .with_for_update()
        ).scalar_one()
        if not self._scope_matches(observation, payload):
            raise DBIInspectionConflict("Una corrección no puede cambiar el alcance.")

        latest = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .where(DBIFieldObservationVersionRecord.observation_id == observation.id)
            .order_by(DBIFieldObservationVersionRecord.version.desc())
            .limit(1)
        ).scalar_one()
        if latest.id != base.id:
            raise DBIInspectionConflict(
                "base_version_id no es la versión vigente; se rechaza el fork."
            )

        self._validate_sampling_point_scope(payload)
        version_id = version_id or uuid4()
        if self._session.get(DBIFieldObservationVersionRecord, version_id) is not None:
            raise DBIInspectionConflict("version_id ya existe.")

        corrected = self._new_version_record(
            observation_id=observation.id,
            version_id=version_id,
            version=latest.version + 1,
            supersedes_version_id=latest.id,
            correction_reason=request.correction_reason,
            payload=payload,
            recorded_by_ref=actor,
        )
        self._session.add(corrected)
        self._session.flush()
        return self._to_contract(corrected)

    def get_latest(
        self,
        *,
        observation_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIFieldObservationVersion | None:
        row = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .join(
                DBIFieldObservationRecord,
                DBIFieldObservationRecord.id
                == DBIFieldObservationVersionRecord.observation_id,
            )
            .where(
                DBIFieldObservationRecord.id == observation_id,
                DBIFieldObservationRecord.tenant_ref == tenant_ref,
                DBIFieldObservationRecord.farm_id == farm_id,
                DBIFieldObservationRecord.plot_id == plot_id,
            )
            .order_by(DBIFieldObservationVersionRecord.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._to_contract(row) if row is not None else None

    def list_versions(
        self,
        *,
        observation_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> tuple[DBIFieldObservationVersion, ...]:
        rows = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .join(
                DBIFieldObservationRecord,
                DBIFieldObservationRecord.id
                == DBIFieldObservationVersionRecord.observation_id,
            )
            .where(
                DBIFieldObservationRecord.id == observation_id,
                DBIFieldObservationRecord.tenant_ref == tenant_ref,
                DBIFieldObservationRecord.farm_id == farm_id,
                DBIFieldObservationRecord.plot_id == plot_id,
            )
            .order_by(DBIFieldObservationVersionRecord.version)
        ).scalars().all()
        return tuple(self._to_contract(row) for row in rows)
