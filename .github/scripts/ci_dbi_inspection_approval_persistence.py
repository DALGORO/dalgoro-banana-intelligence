"""Integración real de vínculo y dos firmas INSPECT sobre procedencia MULTI sintética.

CI exclusivamente: PostGIS efímero y fixture de ci_dbi_multi_persistence.py.
Prueba dos principales, dos transacciones, ausencia de trazabilidad, versión
obsoleta, bloqueos y permisos de un rol sin UPDATE sobre vínculos/eventos.
NO abre endpoints ni publica datos.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.campaign_approval_service import (  # noqa: E402
    DBIInspectionCampaignApprovalService,
)
from app.dbi.inspection.campaign_link_service import (  # noqa: E402
    DBIInspectionCampaignLinkService,
)
from app.dbi.inspection.dual_approval import DBIInspectionApprovalConflict  # noqa: E402
from app.dbi.models.inspection import DBIFieldObservationRecord  # noqa: E402
from app.dbi.models.inspection_campaign import (  # noqa: E402
    DBIInspectionApprovalEventRecord, DBIInspectionCampaignLinkRecord,
)

HOST = "127.0.0.1"
DATABASE = "dbi_test"
ROLE = "dbi_test_inspect_signatures"
TENANT = "tenant-multi-ci"
ORG = "organization-multi-ci"
FARM = UUID("10000000-0000-4000-8000-000000000080")
PLOT = UUID("20000000-0000-4000-8000-000000000080")
OBS = UUID("60000000-0000-4000-8000-000000000080")
VERSION = UUID("70000000-0000-4000-8000-000000000081")
CAMPAIGN = UUID("a0000000-0000-4000-8000-000000000080")
NO_CHAIN_OBS = UUID("60000000-0000-4000-8000-000000000182")
NO_CHAIN_VERSION = UUID("70000000-0000-4000-8000-000000000182")
SUPERSEDING_VERSION = UUID("70000000-0000-4000-8000-000000000183")
EMPTY_SHA = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


def _require_ci() -> None:
    if (
        os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("DBI_ENVIRONMENT") != "test"
        or os.getenv("DBI_INSPECT_APPROVAL_RUN_INTEGRATION") != "1"
    ):
        raise RuntimeError("Esta prueba se prohíbe fuera de GitHub CI efímera.")
    url = os.getenv("DBI_DATABASE_URL", "")
    if url != f"postgresql+psycopg://{ROLE}@{HOST}:5432/{DATABASE}":
        raise RuntimeError("Se requiere el rol/db/host exactos del CI INSPECT.")


def _admin():
    return psycopg.connect(
        host=HOST, dbname=DATABASE, user="postgres",
        autocommit=True, connect_timeout=10,
    )


def _provision() -> None:
    with _admin() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS").format(sql.Identifier(ROLE))
            )
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(DATABASE), sql.Identifier(ROLE),
            )
        )
        for schema in ("dbi", "public"):
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE),
                )
            )
        for table in (
            "dbi_farms", "dbi_plots",
            "dbi_field_observations", "dbi_field_observation_versions",
            "dbi_campaigns", "dbi_inspect_campaign_links",
            "dbi_inspect_approval_events", "dbi_multispectral_extractions",
            "dbi_raster_products", "dbi_analysis_jobs",
            "dbi_analysis_job_attempts", "dbi_analysis_artifacts",
        ):
            cursor.execute(
                sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(ROLE),
                )
            )
        for table in ("dbi_inspect_campaign_links", "dbi_inspect_approval_events"):
            cursor.execute(
                sql.SQL("GRANT INSERT ON dbi.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(ROLE),
                )
            )
        # SELECT FOR UPDATE de la identidad de INSPECT requiere UPDATE de una
        # columna inocua; las tablas de vínculo y firmas quedan sin UPDATE.
        cursor.execute(
            sql.SQL("GRANT UPDATE (created_at) ON "
                    "dbi.dbi_field_observations TO {}").format(sql.Identifier(ROLE))
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                sql.Identifier(ROLE),
            )
        )
        for table in ("dbi_inspect_campaign_links", "dbi_inspect_approval_events"):
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, 'UPDATE'), "
                "has_table_privilege(%s, %s, 'DELETE')",
                (ROLE, "dbi." + table, ROLE, "dbi." + table),
            )
            assert cursor.fetchone() == (False, False), table
        # Segunda observación sin extracción científica: se autoriza la
        # validación de campo, pero se rechaza la firma administrativa.
        cursor.execute(
            """INSERT INTO dbi.dbi_field_observations
               (id, tenant_ref, organization_ref, farm_id, plot_id,
                created_by_ref, created_at)
               VALUES (%s,%s,%s,%s,%s,'ci-no-chain',CURRENT_TIMESTAMP)""",
            (NO_CHAIN_OBS, TENANT, ORG, FARM, PLOT),
        )
        _insert_version(cursor, NO_CHAIN_VERSION, 1, None)


def _insert_version(cursor, version_id: UUID, version: int, supersedes: UUID | None):
    cursor.execute(
        """INSERT INTO dbi.dbi_field_observation_versions
           (id, observation_id, version, supersedes_version_id, schema_version,
            payload_json, payload_sha256, operator_ref, observed_at,
            evidence_kind, correction_reason, recorded_by_ref, created_at)
           VALUES (%s,%s,%s,%s,'dbi-field-observation.v1','{}',%s,
                   'ci-no-chain-operator',CURRENT_TIMESTAMP,'observed',%s,
                   'ci-no-chain',CURRENT_TIMESTAMP)""",
        (version_id, NO_CHAIN_OBS, version, supersedes, EMPTY_SHA,
         "Corrección de campo posterior a firma." if supersedes else None),
    )


def _context(who: str, permissions, *, tenant: str = TENANT, plot: UUID = PLOT):
    return DBIAccessContext(
        principal_ref=who,
        tenant_ref=tenant,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, plot)}),
        permissions=frozenset(permissions),
    )


TECH = _context("technician-signatures-ci", {DBIPermission.READ, DBIPermission.WRITE})
ADMIN = _context(
    "administrator-signatures-ci",
    {DBIPermission.READ, DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC},
)
CLIENT = _context("client-read-only-ci", {DBIPermission.READ})


def _expect(callback, error):
    try:
        callback()
    except error:
        return
    raise AssertionError(f"Debía denegarse: {error.__name__}")


def _params(link_id: UUID):
    return dict(organization_ref=ORG, farm_id=FARM, plot_id=PLOT, link_id=link_id)


def _propose(session: Session, *, actor=TECH, observation=OBS, version=VERSION):
    return DBIInspectionCampaignLinkService(session).propose_link(
        actor, tenant_ref=TENANT, organization_ref=ORG, farm_id=FARM,
        plot_id=PLOT, campaign_id=CAMPAIGN, observation_id=observation,
        observation_version_id=version,
    )


def _validate(engine) -> None:
    with Session(engine) as session:
        _expect(lambda: _propose(session, actor=CLIENT), DBIAccessDenied)
        link, created = _propose(session)
        assert created and link.linked_by_ref == TECH.principal_ref
        primary = link.id
        session.commit()

    # Dos firmas en transacciones reales, cada una derivada del principal
    # autenticado (no de un parámetro actor_ref de frontend).
    with Session(engine) as session:
        service = DBIInspectionCampaignApprovalService(session)
        _expect(
            lambda: service.authorize_administrative(ADMIN, **_params(primary)),
            DBIInspectionApprovalConflict,
        )
        _expect(
            lambda: service.validate_technical(CLIENT, **_params(primary)),
            DBIAccessDenied,
        )
        _expect(
            lambda: service.validate_technical(
                _context(TECH.principal_ref, TECH.permissions, tenant="cross-tenant"),
                **_params(primary),
            ),
            DBIAccessDenied,
        )
        _expect(
            lambda: service.validate_technical(
                _context(TECH.principal_ref, TECH.permissions, plot=NO_CHAIN_OBS),
                **_params(primary),
            ),
            DBIAccessDenied,
        )
        state = service.validate_technical(TECH, **_params(primary))
        assert state.stage == "technical_validated"
        session.commit()

    with Session(engine) as session:
        service = DBIInspectionCampaignApprovalService(session)
        _expect(
            lambda: service.authorize_administrative(
                _context(
                    TECH.principal_ref,
                    {DBIPermission.WRITE, DBIPermission.MANAGE,
                     DBIPermission.APPROVE_AGRONOMIC},
                ),
                **_params(primary),
            ),
            DBIInspectionApprovalConflict,
        )
        for perms in (
            {DBIPermission.MANAGE}, {DBIPermission.APPROVE_AGRONOMIC},
        ):
            _expect(
                lambda p=perms: service.authorize_administrative(
                    _context(ADMIN.principal_ref, p), **_params(primary),
                ),
                DBIAccessDenied,
            )
        link = session.get(DBIInspectionCampaignLinkRecord, primary)
        assert link is not None and service._verified_scientific_chain(link)
        state = service.authorize_administrative(ADMIN, **_params(primary))
        assert state.stage == "dual_approved"
        assert state.technical_by == TECH.principal_ref
        assert state.administrative_by == ADMIN.principal_ref
        session.commit()

    with Session(engine) as session:
        events = session.execute(
            select(DBIInspectionApprovalEventRecord).where(
                DBIInspectionApprovalEventRecord.link_id == primary
            ).order_by(DBIInspectionApprovalEventRecord.decided_at)
        ).scalars().all()
        assert len(events) == 2
        assert [event.event_kind for event in events] == [
            "technical_validated", "administrative_authorized",
        ]
        assert [event.actor_ref for event in events] == [
            TECH.principal_ref, ADMIN.principal_ref,
        ]
        assert events[0].decided_at <= events[1].decided_at
        assert all(e.decided_at.tzinfo is not None for e in events)
        service = DBIInspectionCampaignApprovalService(session)
        _expect(
            lambda: service.validate_technical(TECH, **_params(primary)),
            DBIInspectionApprovalConflict,
        )
        _expect(
            lambda: service.authorize_administrative(ADMIN, **_params(primary)),
            DBIInspectionApprovalConflict,
        )
        assert session.scalar(
            select(func.count(DBIInspectionApprovalEventRecord.id)).where(
                DBIInspectionApprovalEventRecord.link_id == primary
            )
        ) == 2

    # Evidencia de que la firma usa realmente FOR UPDATE sobre observación,
    # evitando carreras entre corrección de campo y aprobación.
    with Session(engine) as locker, Session(engine) as contender:
        locker.execute(
            select(DBIFieldObservationRecord).where(
                DBIFieldObservationRecord.id == OBS,
            ).with_for_update()
        ).scalar_one()
        contender.execute(text("SET LOCAL lock_timeout = '600ms'"))
        try:
            DBIInspectionCampaignApprovalService(contender).validate_technical(
                TECH, **_params(primary),
            )
        except OperationalError as error:
            assert getattr(error.orig, "sqlstate", None) == "55P03"
            contender.rollback()
        else:
            raise AssertionError("Faltó el bloqueo de INSPECT ante corrección concurrente.")
        finally:
            locker.rollback()

    with Session(engine) as session:
        link, created = _propose(
            session, observation=NO_CHAIN_OBS, version=NO_CHAIN_VERSION,
        )
        assert created
        without_chain = link.id
        session.commit()

    with Session(engine) as session:
        service = DBIInspectionCampaignApprovalService(session)
        assert service.validate_technical(TECH, **_params(without_chain)).stage == (
            "technical_validated"
        )
        session.commit()

    with Session(engine) as session:
        service = DBIInspectionCampaignApprovalService(session)
        _expect(
            lambda: service.authorize_administrative(ADMIN, **_params(without_chain)),
            DBIInspectionApprovalConflict,
        )
        session.rollback()

    # Corrección posterior: la firma previa NO sigue siendo vigente.
    with _admin() as connection, connection.cursor() as cursor:
        _insert_version(cursor, SUPERSEDING_VERSION, 2, NO_CHAIN_VERSION)
    with Session(engine) as session:
        _expect(
            lambda: DBIInspectionCampaignApprovalService(session).authorize_administrative(
                ADMIN, **_params(without_chain),
            ),
            DBIInspectionApprovalConflict,
        )
        assert session.scalar(
            select(func.count(DBIInspectionApprovalEventRecord.id)).where(
                DBIInspectionApprovalEventRecord.link_id == without_chain,
                DBIInspectionApprovalEventRecord.event_kind
                == "administrative_authorized",
            )
        ) == 0


if __name__ == "__main__":
    _require_ci()
    _provision()
    engine = create_engine(
        os.environ["DBI_DATABASE_URL"], poolclass=NullPool, future=True,
    )
    try:
        _validate(engine)
    finally:
        engine.dispose()
    print("OK: 2 firmas PostGIS persistidas, actores distintos, versión y MULTI verificadas.")
