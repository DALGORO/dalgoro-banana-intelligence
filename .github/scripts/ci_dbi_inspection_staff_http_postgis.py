"""CI real: INSPECT HTTP + padrón DALGORO + Campaign + lectura cliente PostGIS.

SOLO GITHUB CI con DB/roles fijos efímeros. Aisla el JWT mediante dependencia
FastAPI de prueba, PERO resuelve principal y membresías desde PostgreSQL real.
Sin mocks de StaffWorkflow, directorio, firmas, provenance ni published read.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
os.environ.setdefault("DATABASE_URL", "sqlite:///./ci-inspect-postgis-http-legacy.db")
os.environ.setdefault("JWT_SECRET", "ci-only-inspect-postgis-http")

from app.api.v1 import get_api_router  # noqa: E402
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session  # noqa: E402
from app.dbi.identity import DBIAccessContextResolver, DBIIdentityRepository  # noqa: E402
from app.dbi.inspection.repository import canonical_json, sha256_text  # noqa: E402
from app.dbi.multispectral.repository import DBIMultispectralExtractionRepository  # noqa: E402
from app.dbi.models.inspection_campaign import DBIInspectionApprovalEventRecord  # noqa: E402
from ci_dbi_inspection_persistence import _payload  # noqa: E402
from ci_dbi_multi_persistence import _candidate  # noqa: E402

HOST = "127.0.0.1"
DB = "dbi_test"
ROLE = "dbi_test_inspect_signatures"
MULTI_ROLE = "dbi_test_multispectral"
TENANT = "tenant-multi-ci"
ORG = "organization-multi-ci"
FARM = UUID("10000000-0000-4000-8000-000000000080")
PLOT = UUID("20000000-0000-4000-8000-000000000080")
CAMPAIGN = UUID("a0000000-0000-4000-8000-000000000080")
# Este principal CI tiene el ÚNICO cargo administrator al final del
# test institucional anterior. NO tiene relación con una persona real.
OWNER = UUID("03000000-0000-4000-8000-000000000229")
TECH = UUID("12000000-0000-4000-8000-000000000234")
CLIENT = UUID("13000000-0000-4000-8000-000000000234")
OBS = (
    UUID("14000000-0000-4000-8000-000000000234"),
    UUID("14000000-0000-4000-8000-000000000235"),
    UUID("14000000-0000-4000-8000-000000000236"),
)
VERS = (
    UUID("15000000-0000-4000-8000-000000000234"),
    UUID("15000000-0000-4000-8000-000000000235"),
    UUID("15000000-0000-4000-8000-000000000236"),
)
BASE = f"/api/v1/dbi/organizations/{ORG}/farms/{FARM}/plots/{PLOT}"
LINK_PATH = f"{BASE}/campaigns/{CAMPAIGN}/inspection-links"
PUBLISHED_PATH = f"{BASE}/campaigns/{CAMPAIGN}/published-inspections"


def _guard() -> None:
    if (
        os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("DBI_ENVIRONMENT") != "test"
        or os.getenv("DBI_INSPECT_STAFF_HTTP_POSTGIS") != "1"
        or os.getenv("DBI_DATABASE_URL")
        != f"postgresql+psycopg://{ROLE}@{HOST}:5432/{DB}"
    ):
        raise RuntimeError("Test HTTP INSPECT prohibido fuera de PostGIS efímero de CI.")


def _admin():
    return psycopg.connect(
        host=HOST, dbname=DB, user="postgres", autocommit=True, connect_timeout=10,
    )


def _legacy(who: UUID) -> str:
    return "ci-staff-" + str(who) if who == OWNER else "ci-http-" + str(who)


def _seed() -> None:
    with _admin() as conn, conn.cursor() as cur:
        # Comprobar, sin inventar un segundo administrador, que el fixture
        # previo dejó un único admin activo y su identidad principal válida.
        cur.execute(
            "SELECT principal_id FROM dbi.dbi_inspect_staff_roles "
            "WHERE role='administrator' AND status='active'"
        )
        assert cur.fetchall() == [(OWNER,)]
        for who in (TECH, CLIENT):
            cur.execute(
                "INSERT INTO dbi.dbi_principals (id,legacy_identity_ref,status) "
                "VALUES (%s,%s,'active')",
                (who, _legacy(who)),
            )

        for who, perms in (
            (OWNER, ("read", "write", "approve_agronomic", "manage")),
            (TECH, ("read", "write")),
            # Cliente con permisos DBI potentes SIGUE sin ser personal DALGORO.
            (CLIENT, ("read", "write", "approve_agronomic", "manage")),
        ):
            member = UUID(int=who.int + 1000)
            scope = UUID(int=who.int + 2000)
            cur.execute(
                "INSERT INTO dbi.dbi_memberships "
                "(id, principal_id, tenant_ref, status) VALUES (%s,%s,%s,'active')",
                (member, who, TENANT),
            )
            for permission in perms:
                cur.execute(
                    "INSERT INTO dbi.dbi_membership_permissions "
                    "(membership_id,permission) VALUES (%s,%s)",
                    (member, permission),
                )
            cur.execute(
                "INSERT INTO dbi.dbi_membership_scopes "
                "(id,membership_id,scope_type,organization_ref,farm_id,plot_id) "
                "VALUES (%s,%s,'plot',%s,%s,%s)",
                (scope, member, ORG, FARM, PLOT),
            )
        for who in (OWNER, TECH):
            cur.execute(
                "INSERT INTO dbi.dbi_inspect_staff_roles "
                "(id, principal_id,role,status,accredited_by_ref) "
                "VALUES (%s,%s,'technician','active','ci-postgis-issuer')",
                (UUID(int=who.int+3000), who),
            )

        # Inserción sintética con estructura/huella reales, sin tocar
        # algoritmos científicos ni versiones productivas.
        for index, (observation, version) in enumerate(zip(OBS, VERS)):
            payload = _payload().model_copy(update={
                "tenant_ref": TENANT,
                "organization_ref": ORG,
                "farm_id": FARM,
                "plot_id": PLOT,
                "operator_ref": _legacy(OWNER),
                "up_id": None,
            })
            raw = canonical_json(payload.model_dump(mode="json"))
            cur.execute(
                "INSERT INTO dbi.dbi_field_observations "
                "(id,tenant_ref,organization_ref,farm_id,plot_id,created_by_ref) "
                "VALUES (%s,%s,%s,%s,%s,'ci-http-observer')",
                (observation, TENANT, ORG, FARM, PLOT),
            )
            cur.execute(
                "INSERT INTO dbi.dbi_field_observation_versions "
                "(id,observation_id,version,schema_version,payload_json,"
                "payload_sha256,operator_ref,observed_at,evidence_kind,"
                "recorded_by_ref) VALUES "
                "(%s,%s,1,'dbi-field-observation.v1',%s,%s,%s,%s,'observed',"
                "'ci-http-recorder')",
                (version, observation, raw, sha256_text(raw),
                 payload.operator_ref, payload.observed_at),
            )

        # El rol que firma no puede autoacreditarse ni modificar auditoría.
        for table in (
            "dbi_principals", "dbi_memberships", "dbi_membership_permissions",
            "dbi_membership_scopes", "dbi_inspect_staff_roles",
            "dbi_inspect_staff_audit_events",
        ):
            cur.execute(
                sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(ROLE),
                )
            )
        for table in ("dbi_inspect_staff_roles", "dbi_inspect_staff_audit_events"):
            cur.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT'),"
                "has_table_privilege(%s,%s,'INSERT'),"
                "has_table_privilege(%s,%s,'UPDATE'),"
                "has_table_privilege(%s,%s,'DELETE')",
                (ROLE, "dbi."+table, ROLE, "dbi."+table,
                 ROLE, "dbi."+table, ROLE, "dbi."+table),
            )
            assert cur.fetchone() == (True, False, False, False)

    # Persistir procedencia científica sintética con el adaptador verdadero.
    # Se necesitan dos cadenas para una aprobación única y otra de 2 actores.
    engine = create_engine(
        f"postgresql+psycopg://{MULTI_ROLE}@{HOST}:5432/{DB}",
        poolclass=NullPool,
    )
    try:
        with Session(engine) as session:
            repo = DBIMultispectralExtractionRepository(session)
            for version in VERS[:2]:
                candidate = _candidate().model_copy(
                    update={"observation_version_id": version},
                )
                row, inserted = repo.persist(candidate)
                assert inserted and row.observation_version_id == version
            session.commit()
    finally:
        engine.dispose()


def _make_app(engine, actor):
    os.environ["DBI_INSPECT_STAFF_HTTP_ENABLED"] = "1"
    app = FastAPI()
    app.include_router(get_api_router(), prefix="/api/v1")

    def db_session():
        with Session(engine) as session:
            yield session

    def scoped(session: Session = Depends(get_dbi_session)):
        return DBIAccessContextResolver(
            DBIIdentityRepository(session)
        ).resolve(legacy_identity_ref=_legacy(actor[0]), tenant_ref=TENANT)

    # Aislar SOLO autenticación heredada en esta suite. La identidad DBI,
    # permisos, scope y cargos provienen REALMENTE del motor PostgreSQL.
    app.dependency_overrides[get_dbi_session] = db_session
    app.dependency_overrides[get_dbi_access_context] = scoped
    return app


def _link(client: TestClient, index: int) -> UUID:
    response = client.post(LINK_PATH, json={
        "observation_id": str(OBS[index]),
        "observation_version_id": str(VERS[index]),
    })
    assert response.status_code == 201, response.text
    assert response.json()["created"] is True
    return UUID(response.json()["link_id"])


def _sign_path(link: UUID, kind: str) -> str:
    return f"{BASE}/inspection-links/{link}/{kind}"


def _run() -> None:
    engine = create_engine(os.environ["DBI_DATABASE_URL"], poolclass=NullPool)
    actor = [OWNER]
    try:
        app = _make_app(engine, actor)
        with TestClient(app) as client:
            # Cliente con permisos administrativos DBI NO puede acreditar firma.
            actor[0] = CLIENT
            assert client.post(LINK_PATH, json={
                "observation_id": str(OBS[0]),
                "observation_version_id": str(VERS[0]),
            }).status_code == 404

            actor[0] = OWNER
            dual_link = _link(client, 0)
            response = client.post(_sign_path(
                dual_link, "administrative-authorization",
            ), json={})
            assert response.status_code == 200, response.text
            assert response.json() == {"stage": "self_approved"}

            # Segundo recorrido exige técnico diferente + autorización admin.
            actor[0] = TECH
            second_link = _link(client, 1)
            result = client.post(_sign_path(
                second_link, "technical-validation",
            ), json={})
            assert result.status_code == 200, result.text
            assert result.json() == {"stage": "technical_validated"}
            assert client.post(_sign_path(
                second_link, "administrative-authorization",
            ), json={}).status_code == 404
            actor[0] = OWNER
            result = client.post(_sign_path(
                second_link, "administrative-authorization",
            ), json={})
            assert result.status_code == 200, result.text
            assert result.json() == {"stage": "dual_approved"}

            # Un cliente no ve datos antes de publicar explícitamente
            # Campaign, aunque las firmas ya estén grabadas.
            actor[0] = CLIENT
            assert client.get(PUBLISHED_PATH).status_code == 404
            with _admin() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE dbi.dbi_campaigns SET status='PUBLISHED' "
                    "WHERE id=%s", (CAMPAIGN,),
                )
            approved = client.get(PUBLISHED_PATH)
            assert approved.status_code == 200, approved.text
            rows = approved.json()
            assert len(rows) == 2, rows
            for item in rows:
                assert set(item) == {
                    "observed_at", "foure_state", "foure_value",
                    "yls_state", "yls_value",
                    "functional_leaves_state", "functional_leaves_value",
                }
                assert item["foure_value"] == 3
                assert not any(k in item for k in (
                    "observation_id", "version_id", "operator_ref",
                    "gps_fix", "general_photo", "note", "tenant_ref",
                ))
            # El mismo cliente NO puede pedir otro lote con UUID inventado.
            foreign = PUBLISHED_PATH.replace(str(PLOT), str(VERS[0]))
            assert client.get(foreign).status_code == 404
            # Ni el cliente con permisos DBI elevados puede firmar.
            assert client.post(_sign_path(
                second_link, "administrative-authorization",
            ), json={}).status_code == 404

            # Un cargo técnico revocado no puede volver a validar otro link.
            actor[0] = OWNER
            third_link = _link(client, 2)
            with _admin() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE dbi.dbi_inspect_staff_roles SET status='revoked',"
                    "revoked_by_ref='ci-postgis-issuer',"
                    "revoked_at=CURRENT_TIMESTAMP,"
                    "revocation_reason='ci-http-revocation' "
                    "WHERE principal_id=%s AND role='technician'",
                    (TECH,),
                )
            actor[0] = TECH
            assert client.post(_sign_path(
                third_link, "technical-validation",
            ), json={}).status_code == 404
            with Session(engine) as session:
                assert session.scalar(select(func.count(
                    DBIInspectionApprovalEventRecord.id
                )).where(
                    DBIInspectionApprovalEventRecord.link_id == third_link
                )) == 0

        with Session(engine) as session:
            for link in (dual_link, second_link):
                events = session.execute(
                    select(DBIInspectionApprovalEventRecord).where(
                        DBIInspectionApprovalEventRecord.link_id == link
                    )
                ).scalars().all()
                assert len(events) == 2
                principals = {e.actor_ref for e in events}
                assert principals == (
                    {str(OWNER)} if link == dual_link
                    else {str(OWNER), str(TECH)}
                )
    finally:
        os.environ.pop("DBI_INSPECT_STAFF_HTTP_ENABLED", None)
        engine.dispose()


if __name__ == "__main__":
    _guard()
    _seed()
    _run()
    print("OK: HTTP PostGIS institucional real, firmas 1/2 actores, "
          "revocación, publicación scoped y privacidad cliente.")
