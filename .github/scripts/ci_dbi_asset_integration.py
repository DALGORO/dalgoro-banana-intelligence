"""Ciclo real DBI-ASSET-002 sobre PostgreSQL/PostGIS y S3 efímeros.

El fixture se limita a GitHub Actions, usa identidades y contenido sintéticos,
roles mínimos y endpoints loopback. Nunca admite datos ni proveedores remotos.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from fastapi import HTTPException, Response
from psycopg import sql
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

# La frontera HTTP importa la configuración heredada aunque esta prueba nunca la
# utiliza. Se admite solo una URL SQLite sintética durante el import y se retira
# inmediatamente; una variable heredada del runner falla cerrado.
if os.environ.get("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL no está permitida en esta integración.")
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ.setdefault("JWT_SECRET", "dbi-asset-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

from app.api.v1.dbi_assets import (  # noqa: E402
    confirm_asset_upload,
    register_asset_upload,
    retire_asset,
)
from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.db.dbi_session import (  # noqa: E402
    create_dbi_engine,
    create_dbi_session_factory,
)
from app.dbi.asset_api_schemas import (  # noqa: E402
    DBIAssetConfirmRequest,
    DBIAssetRetireRequest,
    DBIAssetUploadRequest,
)
from app.dbi.asset_repository import DBIAssetRepository  # noqa: E402
from app.dbi.asset_retirement_service import DBIAssetRetirementService  # noqa: E402
from app.dbi.asset_schemas import AnalysisInputAssetRegister  # noqa: E402
from app.dbi.asset_service import DBIAssetService  # noqa: E402
from app.dbi.asset_upload_service import DBIAssetUploadService  # noqa: E402
from app.dbi.asset_verification_service import DBIAssetVerificationService  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.assets import AnalysisInputAsset  # noqa: E402
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageNotFound,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import (  # noqa: E402
    DBIS3ObjectStore,
    DBIS3ObjectStoreConfig,
    build_s3_client,
)

os.environ.pop("DATABASE_URL", None)

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_asset_api"
S3_ENDPOINT = "http://127.0.0.1:8333"
S3_BUCKET = "dbi-ci-synthetic"

TENANT_A = "tenant-ci-asset-a"
TENANT_B = "tenant-ci-asset-b"
ORGANIZATION = "organization-ci-asset"
FARM_A_ID = UUID("71000000-0000-4000-8000-000000000001")
FARM_B_ID = UUID("71000000-0000-4000-8000-000000000002")
PLOT_A_ID = UUID("72000000-0000-4000-8000-000000000001")
ASSET_HAPPY_ID = UUID("73000000-0000-4000-8000-000000000001")
ASSET_RECOVERY_ID = UUID("73000000-0000-4000-8000-000000000002")
ASSET_MISSING_ID = UUID("73000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
PAYLOAD_HAPPY = b"dbi-asset-synthetic-orthophoto"
PAYLOAD_RECOVERY = b"dbi-asset-synthetic-recovery"


class _DiagnosticS3Client:
    """Cuenta operaciones sin registrar argumentos, claves, URLs ni secretos."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.operation_counts: Counter[str] = Counter()
        self.last_operation: str | None = None
        self.last_error_type: str | None = None

    def __getattr__(self, name: str):
        target = getattr(self._delegate, name)
        if not callable(target):
            return target

        def wrapped(*args, **kwargs):
            self.last_operation = name
            self.last_error_type = None
            self.operation_counts[name] += 1
            try:
                return target(*args, **kwargs)
            except Exception as error:
                self.last_error_type = type(error).__name__
                raise

        return wrapped

    @property
    def total_operations(self) -> int:
        return sum(self.operation_counts.values())


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable efímera {name}.")
    return value


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración de activos solo corre en GitHub Actions.")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL no está permitida en esta integración.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración de activos exige ambiente test.")
    if os.environ.get("DBI_ASSET_RUN_INTEGRATION") != "1":
        raise RuntimeError("La integración de activos no fue habilitada explícitamente.")

    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    if identity != (DATABASE, API_ROLE, HOST, PORT):
        raise RuntimeError("La URL DBI no apunta al rol API efímero autorizado.")
    if _required_env("DBI_STORAGE_S3_ENDPOINT_URL") != S3_ENDPOINT:
        raise RuntimeError("El endpoint S3 no es el loopback efímero aprobado.")
    if _required_env("DBI_STORAGE_S3_BUCKET") != S3_BUCKET:
        raise RuntimeError("El bucket S3 no es el fixture sintético aprobado.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _provision_role_and_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (API_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(API_ROLE))
                )

            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE),
                    sql.Identifier(API_ROLE),
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA dbi FROM {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA dbi FROM {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE dbi.dbi_farms, dbi.dbi_plots, "
                    "dbi.dbi_analysis_input_assets TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT ON TABLE dbi.dbi_analysis_input_assets TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, verified_at, updated_at) "
                    "ON TABLE dbi.dbi_analysis_input_assets TO {}"
                ).format(sql.Identifier(API_ROLE))
            )

            cursor.executemany(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    (
                        FARM_A_ID,
                        ORGANIZATION,
                        "CI-ASSET-A",
                        "CI Asset Farm A",
                        NOW,
                        NOW,
                    ),
                    (
                        FARM_B_ID,
                        ORGANIZATION,
                        "CI-ASSET-B",
                        "CI Asset Farm B",
                        NOW,
                        NOW,
                    ),
                ),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-ASSET-PLOT', 'CI Asset Plot', NULL, NULL,
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_A_ID, FARM_A_ID, NOW, NOW),
            )


def _validate_role_capabilities() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                       rolbypassrls
                FROM pg_roles
                WHERE rolname = %s
                """,
                (API_ROLE,),
            )
            if cursor.fetchone() != (False, False, False, False, False):
                raise AssertionError("El rol de activos conserva capacidades globales.")

            checks = {
                "schema_usage": "has_schema_privilege(%s, 'dbi', 'USAGE')",
                "schema_create": "has_schema_privilege(%s, 'dbi', 'CREATE')",
                "asset_select": (
                    "has_table_privilege(%s, "
                    "'dbi.dbi_analysis_input_assets', 'SELECT')"
                ),
                "asset_insert": (
                    "has_table_privilege(%s, "
                    "'dbi.dbi_analysis_input_assets', 'INSERT')"
                ),
                "asset_delete": (
                    "has_table_privilege(%s, "
                    "'dbi.dbi_analysis_input_assets', 'DELETE')"
                ),
                "asset_table_update": (
                    "has_table_privilege(%s, "
                    "'dbi.dbi_analysis_input_assets', 'UPDATE')"
                ),
                "status_update": (
                    "has_column_privilege(%s, 'dbi.dbi_analysis_input_assets', "
                    "'status', 'UPDATE')"
                ),
                "verified_at_update": (
                    "has_column_privilege(%s, 'dbi.dbi_analysis_input_assets', "
                    "'verified_at', 'UPDATE')"
                ),
                "updated_at_update": (
                    "has_column_privilege(%s, 'dbi.dbi_analysis_input_assets', "
                    "'updated_at', 'UPDATE')"
                ),
                "object_key_update": (
                    "has_column_privilege(%s, 'dbi.dbi_analysis_input_assets', "
                    "'object_key', 'UPDATE')"
                ),
                "farm_select": (
                    "has_table_privilege(%s, 'dbi.dbi_farms', 'SELECT')"
                ),
                "farm_insert": (
                    "has_table_privilege(%s, 'dbi.dbi_farms', 'INSERT')"
                ),
                "plot_select": (
                    "has_table_privilege(%s, 'dbi.dbi_plots', 'SELECT')"
                ),
                "plot_insert": (
                    "has_table_privilege(%s, 'dbi.dbi_plots', 'INSERT')"
                ),
            }
            results: dict[str, bool] = {}
            for name, expression in checks.items():
                cursor.execute(f"SELECT {expression}", (API_ROLE,))
                results[name] = bool(cursor.fetchone()[0])

    expected = {
        "schema_usage",
        "asset_select",
        "asset_insert",
        "status_update",
        "verified_at_update",
        "updated_at_update",
        "farm_select",
        "plot_select",
    }
    enabled = {name for name, value in results.items() if value}
    if enabled != expected:
        raise AssertionError(
            "La matriz del rol de activos no es mínima y exacta: "
            f"{sorted(enabled)!r}."
        )


def _context(
    *,
    tenant_ref: str,
    farm_id: UUID,
    include_plot: bool,
) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref=f"principal-{tenant_ref}",
        tenant_ref=tenant_ref,
        organization_refs=frozenset({ORGANIZATION}),
        farm_scopes=frozenset(
            {
                DBIFarmScope(
                    organization_ref=ORGANIZATION,
                    farm_id=farm_id,
                )
            }
        ),
        plot_scopes=(
            frozenset(
                {
                    DBIPlotScope(
                        organization_ref=ORGANIZATION,
                        farm_id=farm_id,
                        plot_id=PLOT_A_ID,
                    )
                }
            )
            if include_plot
            else frozenset()
        ),
        permissions=frozenset({DBIPermission.WRITE}),
    )


def _asset_request(
    *,
    asset_id: UUID,
    payload: bytes,
) -> AnalysisInputAssetRegister:
    return AnalysisInputAssetRegister(
        asset_id=asset_id,
        plot_id=PLOT_A_ID,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=len(payload),
        sha256=sha256(payload).hexdigest(),
        crs="EPSG:32717",
    )


def _register(
    factory,
    store: DBIS3ObjectStore,
    context: DBIAccessContext,
    *,
    farm_id: UUID,
    request: AnalysisInputAssetRegister,
):
    session = factory()
    try:
        http_response = Response()
        result = register_asset_upload(
            payload=DBIAssetUploadRequest(
                organization_ref=ORGANIZATION,
                farm_id=farm_id,
                asset=request,
            ),
            response=http_response,
            session=session,
            context=context,
            store=store,
            service=DBIAssetUploadService(
                DBIAssetService(DBIAssetRepository(session)),
                store,
            ),
        )
        return result, http_response.status_code
    finally:
        session.close()


def _confirm(
    factory,
    store: DBIS3ObjectStore,
    context: DBIAccessContext,
    *,
    farm_id: UUID,
    asset_id: UUID,
):
    session = factory()
    try:
        return confirm_asset_upload(
            asset_id=asset_id,
            payload=DBIAssetConfirmRequest(
                organization_ref=ORGANIZATION,
                farm_id=farm_id,
            ),
            session=session,
            context=context,
            service=DBIAssetVerificationService(
                DBIAssetRepository(session),
                store,
            ),
        )
    finally:
        session.close()


def _retire(
    factory,
    store: DBIS3ObjectStore,
    context: DBIAccessContext,
    *,
    farm_id: UUID,
    asset_id: UUID,
):
    session = factory()
    try:
        return retire_asset(
            asset_id=asset_id,
            payload=DBIAssetRetireRequest(
                organization_ref=ORGANIZATION,
                farm_id=farm_id,
            ),
            session=session,
            context=context,
            service=DBIAssetRetirementService(
                DBIAssetRepository(session),
                store,
            ),
        )
    finally:
        session.close()


def _asset_status(factory, *, tenant_ref: str, farm_id: UUID, asset_id: UUID) -> str:
    session = factory()
    try:
        row = session.scalar(
            select(AnalysisInputAsset).where(
                AnalysisInputAsset.tenant_ref == tenant_ref,
                AnalysisInputAsset.farm_id == farm_id,
                AnalysisInputAsset.id == asset_id,
            )
        )
        if row is None:
            raise AssertionError("El activo sintético esperado no existe.")
        return row.status
    finally:
        session.close()


def _expect_http(status_code: int, callback) -> None:
    try:
        callback()
    except HTTPException as error:
        if error.status_code != status_code:
            raise AssertionError(
                f"Se esperaba HTTP {status_code} y se obtuvo {error.status_code}."
            ) from error
        return
    raise AssertionError(f"Se esperaba HTTP {status_code}.")


def _expect_storage_not_found(callback) -> None:
    try:
        callback()
    except DBIStorageNotFound:
        return
    raise AssertionError("El objeto retirado no debía seguir activo.")


def _signed_put(url: str, headers: dict[str, str], payload: bytes) -> None:
    request = Request(
        url,
        data=payload,
        headers=headers,
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in {200, 201, 204}:
            raise AssertionError("La carga firmada no fue aceptada.")
        response.read()


def _rejected_incomplete_put(
    url: str,
    headers: dict[str, str],
    payload: bytes,
) -> None:
    incomplete_headers = dict(headers)
    incomplete_headers.pop("x-amz-meta-dbi-sha256")
    request = Request(
        url,
        data=payload[:-1],
        headers=incomplete_headers,
        method="PUT",
    )
    try:
        urlopen(request, timeout=10)
    except HTTPError as error:
        if error.code not in {400, 403}:
            raise
        error.close()
        return
    raise AssertionError("La carga incompleta debía ser rechazada.")


def _build_store() -> tuple[DBIS3ObjectStore, _DiagnosticS3Client]:
    config = DBIS3ObjectStoreConfig(
        endpoint_url=_required_env("DBI_STORAGE_S3_ENDPOINT_URL"),
        bucket=_required_env("DBI_STORAGE_S3_BUCKET"),
        region="us-east-1",
        access_key_id=_required_env("AWS_ACCESS_KEY_ID"),
        secret_access_key=_required_env("AWS_SECRET_ACCESS_KEY"),
        verify_tls=True,
        connect_timeout_seconds=3,
        read_timeout_seconds=10,
        max_attempts=2,
        max_object_size_bytes=1024 * 1024,
    )
    diagnostic = _DiagnosticS3Client(build_s3_client(config))
    return DBIS3ObjectStore(config, client=diagnostic), diagnostic


def _simulate_commit_failure(
    factory,
    store: DBIS3ObjectStore,
    context: DBIAccessContext,
) -> None:
    session = factory()
    try:
        evidence = DBIAssetRetirementService(
            DBIAssetRepository(session),
            store,
        ).retire(
            context,
            organization_ref=ORGANIZATION,
            farm_id=FARM_A_ID,
            asset_id=ASSET_HAPPY_ID,
            retired_at=datetime.now(timezone.utc),
        )
        if not evidence.object_changed or not evidence.state_changed:
            raise AssertionError("El primer retiro debía cambiar objeto y fila.")
        session.rollback()
    finally:
        session.close()


def _write_summary(summary: dict[str, object]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    operations = summary["provider_operations"]
    with open(summary_path, "a", encoding="utf-8") as stream:
        stream.write("## DBI-ASSET-002 · integración conjunta\n\n")
        stream.write(
            f"- Latencia total: `{summary['latency_ms']:.2f} ms`\n"
        )
        stream.write(
            f"- Bytes sintéticos cargados: `{summary['bytes_uploaded']}`\n"
        )
        stream.write(
            f"- Conflictos controlados: `{summary['conflicts']}`\n"
        )
        stream.write(
            f"- Denegaciones transversales: `{summary['isolation_denials']}`\n"
        )
        stream.write(
            f"- Recuperaciones compensatorias: `{summary['recoveries']}`\n"
        )
        stream.write(
            "- Operaciones S3 observadas: `"
            + json.dumps(operations, sort_keys=True, separators=(",", ":"))
            + "`\n"
        )
        stream.write("- Costo directo de proveedor externo: `USD 0.00`\n")


def main() -> None:
    _require_ci_scope()
    _provision_role_and_fixture()
    _validate_role_capabilities()

    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    store, diagnostic = _build_store()
    started_at = perf_counter()

    context_a = _context(
        tenant_ref=TENANT_A,
        farm_id=FARM_A_ID,
        include_plot=True,
    )
    context_b = _context(
        tenant_ref=TENANT_B,
        farm_id=FARM_A_ID,
        include_plot=True,
    )
    context_other_farm = _context(
        tenant_ref=TENANT_A,
        farm_id=FARM_B_ID,
        include_plot=False,
    )
    context_without_plot = _context(
        tenant_ref=TENANT_A,
        farm_id=FARM_A_ID,
        include_plot=False,
    )

    try:
        happy_request = _asset_request(
            asset_id=ASSET_HAPPY_ID,
            payload=PAYLOAD_HAPPY,
        )
        happy_upload, happy_status = _register(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            request=happy_request,
        )
        if not happy_upload.created or happy_status != 201:
            raise AssertionError("El registro inicial debía crear el activo.")
        _signed_put(
            happy_upload.upload.url,
            happy_upload.upload.headers,
            PAYLOAD_HAPPY,
        )
        happy_confirmation = _confirm(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            asset_id=ASSET_HAPPY_ID,
        )
        if happy_confirmation.status != "verified" or not happy_confirmation.changed:
            raise AssertionError("El activo cargado debía quedar verificado.")

        operations_before_retry = diagnostic.total_operations
        _expect_http(
            409,
            lambda: _register(
                factory,
                store,
                context_a,
                farm_id=FARM_A_ID,
                request=happy_request,
            ),
        )
        if diagnostic.total_operations != operations_before_retry:
            raise AssertionError(
                "El reintento verificado no debía contactar al proveedor."
            )

        isolation_callbacks = (
            lambda: _confirm(
                factory,
                store,
                context_b,
                farm_id=FARM_A_ID,
                asset_id=ASSET_HAPPY_ID,
            ),
            lambda: _confirm(
                factory,
                store,
                context_other_farm,
                farm_id=FARM_B_ID,
                asset_id=ASSET_HAPPY_ID,
            ),
            lambda: _confirm(
                factory,
                store,
                context_without_plot,
                farm_id=FARM_A_ID,
                asset_id=ASSET_HAPPY_ID,
            ),
        )
        operations_before_isolation = diagnostic.total_operations
        for callback in isolation_callbacks:
            _expect_http(404, callback)
        if diagnostic.total_operations != operations_before_isolation:
            raise AssertionError(
                "Una lectura transversal no debía contactar al proveedor."
            )

        recovery_request = _asset_request(
            asset_id=ASSET_RECOVERY_ID,
            payload=PAYLOAD_RECOVERY,
        )
        recovery_upload, recovery_status = _register(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            request=recovery_request,
        )
        if not recovery_upload.created or recovery_status != 201:
            raise AssertionError("El activo de recuperación debía crearse.")
        _rejected_incomplete_put(
            recovery_upload.upload.url,
            recovery_upload.upload.headers,
            PAYLOAD_RECOVERY,
        )
        _expect_http(
            409,
            lambda: _confirm(
                factory,
                store,
                context_a,
                farm_id=FARM_A_ID,
                asset_id=ASSET_RECOVERY_ID,
            ),
        )
        if (
            _asset_status(
                factory,
                tenant_ref=TENANT_A,
                farm_id=FARM_A_ID,
                asset_id=ASSET_RECOVERY_ID,
            )
            != "registered"
        ):
            raise AssertionError("La carga incompleta alteró el estado DBI.")

        recovered_upload, recovered_status = _register(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            request=recovery_request,
        )
        if recovered_upload.created or recovered_status != 200:
            raise AssertionError("La recuperación debía reutilizar el registro.")
        _signed_put(
            recovered_upload.upload.url,
            recovered_upload.upload.headers,
            PAYLOAD_RECOVERY,
        )
        recovered_confirmation = _confirm(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            asset_id=ASSET_RECOVERY_ID,
        )
        if recovered_confirmation.status != "verified":
            raise AssertionError("La recuperación debía verificar el activo.")

        _simulate_commit_failure(factory, store, context_a)
        if (
            _asset_status(
                factory,
                tenant_ref=TENANT_A,
                farm_id=FARM_A_ID,
                asset_id=ASSET_HAPPY_ID,
            )
            != "verified"
        ):
            raise AssertionError("El rollback simulado modificó la fila DBI.")
        _expect_storage_not_found(
            lambda: store.stat(
                DBIStoragePolicy.build_address(
                    tenant_ref=TENANT_A,
                    purpose=DBIStoragePurpose.ANALYSIS_INPUT,
                    object_id=ASSET_HAPPY_ID,
                )
            )
        )

        happy_retired = _retire(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            asset_id=ASSET_HAPPY_ID,
        )
        if happy_retired.status != "retired" or not happy_retired.changed:
            raise AssertionError("El reintento de retiro debía completar la fila.")

        recovered_retired = _retire(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            asset_id=ASSET_RECOVERY_ID,
        )
        if recovered_retired.status != "retired":
            raise AssertionError("El activo recuperado debía retirarse.")

        missing_request = _asset_request(
            asset_id=ASSET_MISSING_ID,
            payload=b"dbi-asset-synthetic-missing",
        )
        missing_upload, missing_status = _register(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            request=missing_request,
        )
        if not missing_upload.created or missing_status != 201:
            raise AssertionError("El activo sin objeto debía registrarse.")
        missing_retired = _retire(
            factory,
            store,
            context_a,
            farm_id=FARM_A_ID,
            asset_id=ASSET_MISSING_ID,
        )
        if missing_retired.status != "retired" or not missing_retired.changed:
            raise AssertionError("El retiro sin objeto debía completar la fila.")

        final_statuses = {
            _asset_status(
                factory,
                tenant_ref=TENANT_A,
                farm_id=FARM_A_ID,
                asset_id=asset_id,
            )
            for asset_id in (
                ASSET_HAPPY_ID,
                ASSET_RECOVERY_ID,
                ASSET_MISSING_ID,
            )
        }
        if final_statuses != {"retired"}:
            raise AssertionError("El ciclo conjunto dejó estados divergentes.")
    finally:
        engine.dispose()

    summary: dict[str, object] = {
        "latency_ms": round((perf_counter() - started_at) * 1000, 2),
        "bytes_uploaded": len(PAYLOAD_HAPPY) + len(PAYLOAD_RECOVERY),
        "conflicts": 2,
        "isolation_denials": 3,
        "recoveries": 2,
        "missing_object_retirements": 1,
        "assets_retired": 3,
        "provider_operations": dict(sorted(diagnostic.operation_counts.items())),
        "external_provider_cost_usd": 0.0,
    }
    _write_summary(summary)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    print("Ciclo DBI-ASSET-002 real aprobado con DB y S3 efímeros.")


if __name__ == "__main__":
    main()
