"""Valida persistencia idempotente y locking de activos DBI offline."""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.asset_registration import (  # noqa: E402
    DBIAssetRegistrationAction,
    DBIAssetRegistrationConflict,
    DBIAssetRegistrationIntent,
    build_asset_registration_plan,
)
from app.dbi.asset_repository import DBIAssetRepository  # noqa: E402
from app.dbi.models.assets import AnalysisInputAsset  # noqa: E402

ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
FARM_ID = UUID("22222222-2222-4222-8222-222222222222")
PLOT_ID = UUID("33333333-3333-4333-8333-333333333333")


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def _intent() -> DBIAssetRegistrationIntent:
    return DBIAssetRegistrationIntent(
        asset_id=ASSET_ID,
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=4096,
        sha256="a" * 64,
        crs="EPSG:32717",
        created_by_ref="principal-a",
    )


def _row(plan, *, content_type: str | None = None) -> AnalysisInputAsset:
    return AnalysisInputAsset(
        id=plan.asset_id,
        tenant_ref=plan.tenant_ref,
        farm_id=plan.farm_id,
        plot_id=plan.plot_id,
        asset_kind=plan.asset_kind,
        status="registered",
        object_key=plan.metadata.address.object_key,
        content_type=content_type or plan.metadata.content_type,
        size_bytes=plan.metadata.size_bytes,
        sha256=plan.metadata.sha256,
        crs=plan.crs,
        created_by_ref=plan.created_by_ref,
        verified_at=None,
    )


def _session(results: list[object], statements: list[object]) -> Session:
    session = Session()

    def execute(self, statement):
        statements.append(statement)
        if not results:
            raise AssertionError("No había resultado preparado para execute().")
        return ScalarResult(results.pop(0))

    session.execute = MethodType(execute, session)  # type: ignore[method-assign]
    return session


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )


def validate_insert() -> None:
    plan = build_asset_registration_plan(intent=_intent(), existing=None)
    statements: list[object] = []
    session = _session([ASSET_ID], statements)
    repository = DBIAssetRepository(session)
    persisted = repository.persist_registration(plan=plan)
    assert persisted == plan
    assert persisted.created is True
    assert len(statements) == 1
    sql = _sql(statements[0])
    assert "INSERT INTO dbi_analysis_input_assets" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "RETURNING dbi_analysis_input_assets.id" in sql
    assert "commit" not in sql.lower()
    session.close()


def validate_concurrent_exact_retry() -> None:
    plan = build_asset_registration_plan(intent=_intent(), existing=None)
    statements: list[object] = []
    session = _session([None, _row(plan)], statements)
    repository = DBIAssetRepository(session)
    persisted = repository.persist_registration(plan=plan)
    assert persisted.action is DBIAssetRegistrationAction.REUSE
    assert persisted.status == "registered"
    assert persisted.created is False
    assert len(statements) == 2
    select_sql = _sql(statements[1])
    assert "FOR UPDATE" in select_sql
    assert "tenant_ref" in select_sql
    assert "farm_id" in select_sql
    assert "dbi_analysis_input_assets.id" in select_sql
    session.close()


def validate_reuse_plan() -> None:
    create = build_asset_registration_plan(intent=_intent(), existing=None)
    existing = _row(create)
    existing.status = "verified"
    existing.verified_at = datetime(
        2026,
        8,
        3,
        1,
        tzinfo=timezone.utc,
    )
    reuse = build_asset_registration_plan(
        intent=_intent(),
        existing=__import__(
            "app.dbi.asset_repository", fromlist=["_snapshot"]
        )._snapshot(existing),
    )
    statements: list[object] = []
    session = _session([existing], statements)
    persisted = DBIAssetRepository(session).persist_registration(plan=reuse)
    assert persisted.action is DBIAssetRegistrationAction.REUSE
    assert persisted.status == "verified"
    assert persisted.created is False
    assert len(statements) == 1
    assert "FOR UPDATE" in _sql(statements[0])
    session.close()


def validate_divergence_and_non_enumeration() -> None:
    plan = build_asset_registration_plan(intent=_intent(), existing=None)
    for results in ([None, None], [None, _row(plan, content_type="application/zip")]):
        statements: list[object] = []
        session = _session(list(results), statements)
        try:
            DBIAssetRepository(session).persist_registration(plan=plan)
        except DBIAssetRegistrationConflict:
            pass
        else:
            raise AssertionError("La persistencia debía fallar cerrada.")
        assert len(statements) == 2
        sql = _sql(statements[1])
        assert "tenant_ref" in sql and "farm_id" in sql and "FOR UPDATE" in sql
        session.close()


def validate_retirement_transition() -> None:
    plan = build_asset_registration_plan(
        intent=_intent(),
        existing=None,
    )
    retired_at = datetime(
        2026,
        8,
        3,
        2,
        30,
        tzinfo=timezone.utc,
    )

    for initial_status in (
        "registered",
        "verified",
        "quarantined",
    ):
        row = _row(plan)
        row.status = initial_status

        if initial_status == "verified":
            row.verified_at = datetime(
                2026,
                8,
                3,
                1,
                tzinfo=timezone.utc,
            )

        previous_verified_at = row.verified_at
        flush_calls: list[bool] = []
        session = Session()

        def flush(self) -> None:
            flush_calls.append(True)

        session.flush = MethodType(  # type: ignore[method-assign]
            flush,
            session,
        )

        repository = DBIAssetRepository(session)

        assert repository.apply_retirement(
            row=row,
            retired_at=retired_at,
        ) is True
        assert row.status == "retired"
        assert row.updated_at == retired_at
        assert row.verified_at == previous_verified_at
        assert len(flush_calls) == 1

        assert repository.apply_retirement(
            row=row,
            retired_at=retired_at,
        ) is False
        assert len(flush_calls) == 1

        session.close()

    invalid_row = _row(plan)
    invalid_row.status = "invalid"
    invalid_session = Session()
    invalid_repository = DBIAssetRepository(invalid_session)

    try:
        invalid_repository.apply_retirement(
            row=invalid_row,
            retired_at=retired_at,
        )
    except DBIAssetRegistrationConflict:
        pass
    else:
        raise AssertionError(
            "Un estado desconocido no debía admitir retiro."
        )
    finally:
        invalid_session.close()

    naive_row = _row(plan)
    naive_session = Session()
    naive_repository = DBIAssetRepository(naive_session)

    try:
        naive_repository.apply_retirement(
            row=naive_row,
            retired_at=datetime(2026, 8, 3, 2, 30),
        )
    except DBIAssetRegistrationConflict:
        pass
    else:
        raise AssertionError(
            "retired_at debía exigir zona horaria."
        )
    finally:
        naive_session.close()


def validate_static_boundaries() -> None:
    path = BACKEND_ROOT / "app" / "dbi" / "asset_repository.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {"fastapi", "boto3", "botocore", "requests", "httpx"}.isdisjoint(roots)
    for forbidden in (".commit(", ".rollback(", "SessionLocal", "DATABASE_URL", "object_store"):
        assert forbidden not in source
    assert ".with_for_update()" in source
    assert ".on_conflict_do_nothing()" in source


def main() -> None:
    validate_insert()
    validate_concurrent_exact_retry()
    validate_reuse_plan()
    validate_divergence_and_non_enumeration()
    validate_retirement_transition()
    validate_static_boundaries()
    print("Repositorio idempotente de activos DBI validado offline.")


if __name__ == "__main__":
    main()
