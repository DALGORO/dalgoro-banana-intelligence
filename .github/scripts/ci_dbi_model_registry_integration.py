"""Prueba DBI-ML-001 en PostgreSQL/PostGIS efímero con rol mínimo."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.model_registry import (  # noqa: E402
    AnalysisProfileRegistration,
    AnalysisProfileRole,
    AnalysisProfileStatus,
    DBIModelRegistryAnalysisProfilePolicy,
    DBIModelRegistryRepository,
    DBIModelRegistryService,
    ModelLifecycleStatus,
    ModelRegistryConflict,
    ModelVersionRegistration,
    PipelineConfigRegistration,
)
from app.dbi.models.model_registry import (  # noqa: E402
    DBIAnalysisProfile,
    DBIModelGovernanceEvent,
    DBIModelVersion,
    DBIPipelineConfigVersion,
)
from app.dbi.jobs.service_contracts import (  # noqa: E402
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
)

HOST = "127.0.0.1"
PORT = 5432
DBI_DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_model_registry_api"
NOW = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)
FARM_ID = UUID("10000000-0000-0000-0000-000000000001")
PLOT_ID = UUID("20000000-0000-0000-0000-000000000001")


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración ML sólo corre en GitHub Actions.")
    if os.environ.get("DBI_MODEL_REGISTRY_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_MODEL_REGISTRY_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración ML exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if API_ROLE not in url or HOST not in url or DBI_DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol/fixture ML autorizado.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DBI_DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _provision_minimal_role() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (API_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(API_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DBI_DATABASE), sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            for table_name in (
                "dbi_model_versions",
                "dbi_pipeline_config_versions",
                "dbi_analysis_profiles",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT, INSERT, UPDATE ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(API_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT ON dbi.dbi_model_governance_events TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(API_ROLE)
                )
            )


def _engine():
    return create_engine(
        os.environ["DBI_DATABASE_URL"],
        poolclass=NullPool,
        future=True,
    )


def _service(session: Session) -> DBIModelRegistryService:
    return DBIModelRegistryService(DBIModelRegistryRepository(session))


def _register_approved_model(
    session: Session,
    *,
    suffix: str,
    at: datetime,
):
    service = _service(session)
    registration = ModelVersionRegistration(
        model_family="banana_detection",
        model_version=f"yolov8_{suffix}",
        training_dataset_version=f"train_{suffix}",
        validation_dataset_version=f"validation_{suffix}",
        input_contract_version="orthophoto_tiles_v1",
        output_contract_version="banana_detections_v1",
        artifact_ref=f"artifact_{suffix}",
        metrics={"map50": 0.91, "precision": 0.93, "recall": 0.89},
    )
    created = service.register_model(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at,
    )
    replay = service.register_model(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at + timedelta(seconds=1),
    )
    assert created.created is True and replay.created is False
    service.validate_model(
        model_id=created.snapshot.model_id,
        actor_ref="actor_ml_ci",
        changed_at=at + timedelta(seconds=2),
    )
    service.approve_model(
        model_id=created.snapshot.model_id,
        actor_ref="actor_ml_approver",
        approved_at=at + timedelta(seconds=3),
    )
    return created.snapshot.model_id


def _register_approved_pipeline(
    session: Session,
    *,
    suffix: str,
    at: datetime,
):
    service = _service(session)
    registration = PipelineConfigRegistration(
        model_family="banana_detection",
        config_version=f"density_{suffix}",
        config={
            "tile_size": 640,
            "confidence": 0.35,
            "iou": 0.45,
            "deduplication": {"enabled": True, "radius_px": 28},
        },
    )
    created = service.register_pipeline_config(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at,
    )
    replay = service.register_pipeline_config(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at + timedelta(seconds=1),
    )
    assert created.created is True and replay.created is False
    service.validate_pipeline_config(
        pipeline_config_id=created.snapshot.pipeline_config_id,
        actor_ref="actor_ml_ci",
        changed_at=at + timedelta(seconds=2),
    )
    service.approve_pipeline_config(
        pipeline_config_id=created.snapshot.pipeline_config_id,
        actor_ref="actor_ml_approver",
        approved_at=at + timedelta(seconds=3),
    )
    return created.snapshot.pipeline_config_id


def _register_profile(
    session: Session,
    *,
    tenant_ref: str,
    policy_ref: str,
    model_id: UUID,
    pipeline_id: UUID,
    at: datetime,
):
    service = _service(session)
    registration = AnalysisProfileRegistration(
        tenant_ref=tenant_ref,
        model_family="banana_detection",
        model_version_id=model_id,
        pipeline_config_id=pipeline_id,
        policy_ref=policy_ref,
    )
    created = service.register_challenger(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at,
    )
    replay = service.register_challenger(
        registration,
        actor_ref="actor_ml_ci",
        created_at=at + timedelta(seconds=1),
    )
    assert created.created is True and replay.created is False
    return created.snapshot.profile_id


def _context(tenant_ref: str) -> AnalysisProfileResolutionContext:
    return AnalysisProfileResolutionContext(
        tenant_ref=tenant_ref,
        organization_ref="organization_ml_ci",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
    )


def validate_lifecycle_and_rollback(engine) -> tuple[UUID, UUID]:
    with Session(engine) as session:
        model_a = _register_approved_model(session, suffix="a", at=NOW)
        pipeline_a = _register_approved_pipeline(
            session, suffix="a", at=NOW + timedelta(minutes=1)
        )
        profile_a = _register_profile(
            session,
            tenant_ref="tenant_ml_ci",
            policy_ref="policy_a",
            model_id=model_a,
            pipeline_id=pipeline_a,
            at=NOW + timedelta(minutes=2),
        )
        policy = DBIModelRegistryAnalysisProfilePolicy(
            DBIModelRegistryRepository(session)
        )
        try:
            policy.resolve(context=_context("tenant_ml_ci"))
        except AnalysisProfileUnavailable:
            pass
        else:
            raise AssertionError("Un Challenger no puede resolver como Champion.")

        changed = _service(session).promote_challenger(
            tenant_ref="tenant_ml_ci",
            model_family="banana_detection",
            profile_id=profile_a,
            actor_ref="actor_ml_approver",
            promoted_at=NOW + timedelta(minutes=3),
        )
        assert changed.changed is True
        session.commit()

    with Session(engine) as session:
        resolved = DBIModelRegistryAnalysisProfilePolicy(
            DBIModelRegistryRepository(session)
        ).resolve(context=_context("tenant_ml_ci"))
        assert resolved.model_version_id == "yolov8_a"
        assert resolved.pipeline_config_version == "density_a"
        assert resolved.policy_ref == "policy_a"
        session.commit()

    with Session(engine) as session:
        model_b = _register_approved_model(
            session, suffix="b", at=NOW + timedelta(minutes=4)
        )
        pipeline_b = _register_approved_pipeline(
            session, suffix="b", at=NOW + timedelta(minutes=5)
        )
        profile_b = _register_profile(
            session,
            tenant_ref="tenant_ml_ci",
            policy_ref="policy_b",
            model_id=model_b,
            pipeline_id=pipeline_b,
            at=NOW + timedelta(minutes=6),
        )
        service = _service(session)
        service.promote_challenger(
            tenant_ref="tenant_ml_ci",
            model_family="banana_detection",
            profile_id=profile_b,
            actor_ref="actor_ml_approver",
            promoted_at=NOW + timedelta(minutes=7),
        )
        service.promote_challenger(
            tenant_ref="tenant_ml_ci",
            model_family="banana_detection",
            profile_id=profile_a,
            actor_ref="actor_ml_approver",
            promoted_at=NOW + timedelta(minutes=8),
        )
        service.retire_profile(
            profile_id=profile_b,
            actor_ref="actor_ml_approver",
            retired_at=NOW + timedelta(minutes=9),
        )
        service.retire_model(
            model_id=model_b,
            actor_ref="actor_ml_approver",
            retired_at=NOW + timedelta(minutes=10),
        )
        service.retire_pipeline_config(
            pipeline_config_id=pipeline_b,
            actor_ref="actor_ml_approver",
            retired_at=NOW + timedelta(minutes=11),
        )
        session.commit()

    with Session(engine) as session:
        champion = session.execute(
            select(DBIAnalysisProfile).where(
                DBIAnalysisProfile.tenant_ref == "tenant_ml_ci",
                DBIAnalysisProfile.role == AnalysisProfileRole.CHAMPION.value,
                DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
            )
        ).scalar_one()
        assert champion.id == profile_a
        retired_model = session.get(DBIModelVersion, model_b)
        retired_pipeline = session.get(DBIPipelineConfigVersion, pipeline_b)
        assert retired_model is not None and retired_model.status == ModelLifecycleStatus.RETIRED.value
        assert retired_pipeline is not None and retired_pipeline.status == ModelLifecycleStatus.RETIRED.value
        promotions = session.execute(
            select(func.count())
            .select_from(DBIModelGovernanceEvent)
            .where(DBIModelGovernanceEvent.action == "champion_promoted")
        ).scalar_one()
        assert promotions >= 3
        session.commit()
    return model_a, pipeline_a


def validate_tenant_isolation(engine, model_id: UUID, pipeline_id: UUID) -> None:
    with Session(engine) as session:
        profile = _register_profile(
            session,
            tenant_ref="tenant_ml_other",
            policy_ref="policy_other",
            model_id=model_id,
            pipeline_id=pipeline_id,
            at=NOW + timedelta(minutes=20),
        )
        _service(session).promote_challenger(
            tenant_ref="tenant_ml_other",
            model_family="banana_detection",
            profile_id=profile,
            actor_ref="actor_ml_approver",
            promoted_at=NOW + timedelta(minutes=21),
        )
        session.commit()

    with Session(engine) as session:
        other = DBIModelRegistryAnalysisProfilePolicy(
            DBIModelRegistryRepository(session)
        ).resolve(context=_context("tenant_ml_other"))
        original = DBIModelRegistryAnalysisProfilePolicy(
            DBIModelRegistryRepository(session)
        ).resolve(context=_context("tenant_ml_ci"))
        assert other.policy_ref == "policy_other"
        assert original.policy_ref == "policy_a"
        session.commit()


def validate_concurrent_promotions(engine, model_id: UUID, pipeline_id: UUID) -> None:
    tenant = "tenant_ml_concurrent"
    with Session(engine) as session:
        first = _register_profile(
            session,
            tenant_ref=tenant,
            policy_ref="concurrent_a",
            model_id=model_id,
            pipeline_id=pipeline_id,
            at=NOW + timedelta(minutes=30),
        )
        second = _register_profile(
            session,
            tenant_ref=tenant,
            policy_ref="concurrent_b",
            model_id=model_id,
            pipeline_id=pipeline_id,
            at=NOW + timedelta(minutes=31),
        )
        session.commit()

    barrier = Barrier(2)

    def promote(profile_id: UUID, minute: int) -> None:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            _service(session).promote_challenger(
                tenant_ref=tenant,
                model_family="banana_detection",
                profile_id=profile_id,
                actor_ref="actor_ml_concurrent",
                promoted_at=NOW + timedelta(minutes=minute),
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(promote, first, 32),
            executor.submit(promote, second, 33),
        ]
        for future in futures:
            future.result(timeout=20)

    with Session(engine) as session:
        champions = session.execute(
            select(DBIAnalysisProfile.id).where(
                DBIAnalysisProfile.tenant_ref == tenant,
                DBIAnalysisProfile.model_family == "banana_detection",
                DBIAnalysisProfile.role == AnalysisProfileRole.CHAMPION.value,
                DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
            )
        ).scalars().all()
        assert len(champions) == 1
        session.commit()


def validate_minimum_privileges(engine) -> None:
    with engine.connect() as connection:
        current_user = connection.execute(text("SELECT current_user")).scalar_one()
        assert current_user == API_ROLE
        superuser = connection.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        assert superuser is False
        assert connection.execute(
            text(
                "SELECT has_table_privilege(current_user, "
                "'dbi.dbi_model_versions', 'SELECT')"
            )
        ).scalar_one() is True
        assert connection.execute(
            text(
                "SELECT has_table_privilege(current_user, "
                "'dbi.dbi_model_versions', 'DELETE')"
            )
        ).scalar_one() is False
        assert connection.execute(
            text(
                "SELECT has_table_privilege(current_user, "
                "'dbi.dbi_model_governance_events', 'UPDATE')"
            )
        ).scalar_one() is False


def main() -> None:
    _require_scope()
    _provision_minimal_role()
    engine = _engine()
    try:
        validate_minimum_privileges(engine)
        model_id, pipeline_id = validate_lifecycle_and_rollback(engine)
        validate_tenant_isolation(engine, model_id, pipeline_id)
        validate_concurrent_promotions(engine, model_id, pipeline_id)
    finally:
        engine.dispose()
    print("DBI-ML-001 PostGIS aprobado: lineage, rollback, aislamiento y concurrencia.")


if __name__ == "__main__":
    main()
