"""Valida JOB-003 y su frontera HTTP integrada con DBI-QUEUE-001 offline."""

from __future__ import annotations

import inspect
import os
import sys
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "dbi-job-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException, Response  # noqa: E402
from app.api.v1 import dbi_analysis_jobs, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.delivery.metrics import DBIDeliveryMetrics, DBIDeliveryMetricsSnapshot  # noqa: E402
from app.dbi.jobs.metrics import (  # noqa: E402
    DBIAnalysisJobMetrics,
    DBIAnalysisJobMetricsSnapshot,
)
from app.dbi.jobs.persistence_contracts import (  # noqa: E402
    AnalysisJobPersistenceConflict,
    AnalysisJobSnapshot,
)
from app.dbi.jobs.repository import DBIAnalysisJobRepository  # noqa: E402
from app.dbi.jobs.service import (  # noqa: E402
    AnalysisJobCreationEvidence,
    AnalysisJobTransitionEvidence,
    DBIAnalysisJobService,
)
from app.dbi.jobs.service_contracts import (  # noqa: E402
    AnalysisJobCreateRequest,
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
    ApprovedAnalysisProfile,
)
from app.dbi.jobs.state_machine import AnalysisJobStatus, InvalidAnalysisJobTransition  # noqa: E402

FARM_ID = UUID("10000000-0000-0000-0000-000000000001")
PLOT_ID = UUID("20000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("30000000-0000-0000-0000-000000000001")
ORTHO_ID = UUID("40000000-0000-0000-0000-000000000001")
ORTHO_ALT_ID = UUID("40000000-0000-0000-0000-000000000002")
BOUNDARY_ID = UUID("50000000-0000-0000-0000-000000000001")
EXCLUSIONS_ID = UUID("60000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 4, 22, 0, tzinfo=timezone.utc)


def _context(*, submit: bool = True) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-job-ci",
        tenant_ref="tenant-job-ci",
        organization_refs=frozenset({"organization-job-ci"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="organization-job-ci", farm_id=FARM_ID)}
        ),
        plot_scopes=frozenset(
            {DBIPlotScope(organization_ref="organization-job-ci", farm_id=FARM_ID, plot_id=PLOT_ID)}
        ),
        permissions=(
            frozenset({DBIPermission.SUBMIT_ANALYSIS})
            if submit
            else frozenset({DBIPermission.READ})
        ),
    )


def _request(*, orthophoto_asset_id: UUID = ORTHO_ID) -> AnalysisJobCreateRequest:
    return AnalysisJobCreateRequest(
        request_id="request-job-ci",
        campaign_id=CAMPAIGN_ID,
        orthophoto_asset_id=orthophoto_asset_id,
        boundary_asset_id=BOUNDARY_ID,
        exclusions_asset_id=EXCLUSIONS_ID,
    )


class ProfilePolicy:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, *, context: AnalysisProfileResolutionContext) -> ApprovedAnalysisProfile:
        assert context.farm_id == FARM_ID and context.plot_id == PLOT_ID
        self.calls += 1
        return ApprovedAnalysisProfile(
            model_version_id="banana-density-approved-ci",
            pipeline_config_version="pipeline-approved-ci",
            policy_ref="policy-approved-ci",
        )


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.jobs: dict[tuple[str, str], AnalysisJobSnapshot] = {}
        self.current: AnalysisJobSnapshot | None = None
        self.apply_calls = 0

    def require_plot(self, **kwargs) -> None:
        del kwargs
        self.calls.append("require_plot")

    def require_campaign(self, **kwargs) -> None:
        del kwargs
        self.calls.append("require_campaign")

    def require_verified_asset(self, *, asset_kind: str, **kwargs) -> None:
        del kwargs
        self.calls.append(f"asset:{asset_kind}")

    def get_by_request_for_update(self, *, tenant_ref: str, request_id: str):
        self.calls.append("get_by_request")
        return self.jobs.get((tenant_ref, request_id))

    def get_for_update(self, **kwargs):
        del kwargs
        self.calls.append("get_for_update")
        return self.current

    def require_same_intent(self, *, existing, incoming) -> None:
        self.calls.append("require_same_intent")
        DBIAnalysisJobRepository.require_same_intent(existing=existing, incoming=incoming)

    def persist_accepted(self, *, candidate, intent):
        self.calls.append("persist_accepted")
        key = (candidate.tenant_ref, candidate.request_id)
        existing = self.jobs.get(key)
        if existing is not None:
            self.require_same_intent(existing=existing, incoming=intent)
            return existing, False
        self.jobs[key] = candidate
        self.current = candidate
        return candidate, True

    def apply_status(self, *, target_status, changed_at, **kwargs):
        del kwargs
        self.apply_calls += 1
        if self.current is None:
            raise AssertionError("No existe trabajo mutable.")
        self.current = self.current.model_copy(
            update={"status": target_status, "updated_at": changed_at}
        )
        return self.current


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAPIService:
    def __init__(self, *, creation=None, transition=None, error=None) -> None:
        self.creation = creation
        self.transition = transition
        self.error = error

    def create(self, *args, **kwargs):
        del args, kwargs
        if self.error is not None:
            raise self.error
        return self.creation

    def cancel(self, *args, **kwargs):
        del args, kwargs
        if self.error is not None:
            raise self.error
        return self.transition


class FakeDeliveryService:
    def __init__(self, *, created: bool = True, error: Exception | None = None) -> None:
        self.created = created
        self.error = error
        self.calls = 0

    def enqueue_authorized_analysis_command(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(created=self.created)


def _must_http_error(callback, expected_status: int) -> None:
    try:
        callback()
    except HTTPException as error:
        assert error.status_code == expected_status
    else:
        raise AssertionError(f"Se esperaba HTTP {expected_status}.")


def validate_router() -> None:
    methods = {
        (route.path, method)
        for route in get_api_router().routes
        if route.path.startswith("/dbi/")
        for method in route.methods
    }
    for path in (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/jobs",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/cancel",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/retry",
    ):
        assert (path, "POST") in methods
    assert (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}",
        "GET",
    ) in methods


def validate_create_replay_and_authorization() -> AnalysisJobSnapshot:
    repository = FakeRepository()
    policy = ProfilePolicy()
    service = DBIAnalysisJobService(repository)
    created = service.create(
        _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
        plot_id=PLOT_ID, request=_request(), profile_policy=policy, accepted_at=NOW,
    )
    assert created.created is True and created.snapshot.status is AnalysisJobStatus.ACCEPTED
    assert len(created.snapshot.command_sha256) == 64
    assert repository.calls == [
        "get_by_request", "require_plot", "require_campaign",
        "asset:orthophoto", "asset:boundary", "asset:exclusions", "persist_accepted",
    ]
    assert policy.calls == 1

    before = len(repository.calls)
    replay = service.create(
        _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
        plot_id=PLOT_ID, request=_request(), profile_policy=policy,
        accepted_at=NOW + timedelta(seconds=1),
    )
    assert replay.created is False and replay.snapshot.job_id == created.snapshot.job_id
    assert repository.calls[before:] == ["get_by_request", "require_same_intent"]
    assert policy.calls == 1

    try:
        service.create(
            _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
            plot_id=PLOT_ID, request=_request(orthophoto_asset_id=ORTHO_ALT_ID),
            profile_policy=policy, accepted_at=NOW + timedelta(seconds=2),
        )
    except AnalysisJobPersistenceConflict:
        pass
    else:
        raise AssertionError("La misma clave con otra intención debía fallar.")

    denied = FakeRepository()
    try:
        DBIAnalysisJobService(denied).create(
            _context(submit=False), organization_ref="organization-job-ci",
            farm_id=FARM_ID, plot_id=PLOT_ID, request=_request(),
            profile_policy=ProfilePolicy(), accepted_at=NOW,
        )
    except DBIAccessDenied:
        pass
    else:
        raise AssertionError("READ no debe autorizar SUBMIT_ANALYSIS.")
    assert denied.calls == []
    return created.snapshot


def validate_job_state_machine_compatibility(base: AnalysisJobSnapshot) -> None:
    repository = FakeRepository()
    service = DBIAnalysisJobService(repository)
    repository.current = base.model_copy(update={"status": AnalysisJobStatus.QUEUED})
    canceled = service.cancel(
        _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
        job_id=base.job_id, changed_at=NOW + timedelta(minutes=1),
    )
    assert canceled.changed and canceled.snapshot.status is AnalysisJobStatus.CANCEL_REQUESTED
    repeated = service.cancel(
        _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
        job_id=base.job_id, changed_at=NOW + timedelta(minutes=2),
    )
    assert repeated.changed is False and repository.apply_calls == 1

    repository.current = base.model_copy(update={"status": AnalysisJobStatus.ACCEPTED})
    try:
        service.cancel(
            _context(), organization_ref="organization-job-ci", farm_id=FARM_ID,
            job_id=base.job_id, changed_at=NOW + timedelta(minutes=3),
        )
    except InvalidAnalysisJobTransition:
        pass
    else:
        raise AssertionError("accepted no debe cancelar directamente.")


def validate_api_queue_transaction(base: AnalysisJobSnapshot) -> None:
    metrics = DBIAnalysisJobMetrics()
    delivery_metrics = DBIDeliveryMetrics()
    queued_snapshot = base.model_copy(
        update={"status": AnalysisJobStatus.QUEUED, "updated_at": NOW + timedelta(seconds=1)}
    )
    original_reload = dbi_analysis_jobs._reload_job
    dbi_analysis_jobs._reload_job = lambda *args, **kwargs: queued_snapshot
    try:
        session = FakeSession()
        response = Response()
        delivery = FakeDeliveryService(created=True)
        result = dbi_analysis_jobs.create_analysis_job(
            organization_ref="organization-job-ci", farm_id=FARM_ID, plot_id=PLOT_ID,
            payload=_request(), response=response, session=session, context=_context(),
            profile_policy=ProfilePolicy(),
            service=FakeAPIService(
                creation=AnalysisJobCreationEvidence(snapshot=base, created=True)
            ),
            delivery_service=delivery, metrics=metrics, delivery_metrics=delivery_metrics,
        )
        assert response.status_code == 201 and session.commits == 1
        assert result.status is AnalysisJobStatus.QUEUED and delivery.calls == 1
        for forbidden in (
            "command_sha256", "requested_by_ref", "orthophoto_asset_id",
            "boundary_asset_id", "model_version_id",
        ):
            assert forbidden not in result.model_dump(mode="json")

        conflict_session = FakeSession()
        _must_http_error(
            lambda: dbi_analysis_jobs.create_analysis_job(
                organization_ref="organization-job-ci", farm_id=FARM_ID, plot_id=PLOT_ID,
                payload=_request(), response=Response(), session=conflict_session,
                context=_context(), profile_policy=ProfilePolicy(),
                service=FakeAPIService(error=AnalysisJobPersistenceConflict()),
                delivery_service=FakeDeliveryService(), metrics=metrics,
                delivery_metrics=delivery_metrics,
            ),
            409,
        )
        assert conflict_session.rollbacks == 1

        profile_session = FakeSession()
        _must_http_error(
            lambda: dbi_analysis_jobs.create_analysis_job(
                organization_ref="organization-job-ci", farm_id=FARM_ID, plot_id=PLOT_ID,
                payload=_request(), response=Response(), session=profile_session,
                context=_context(), profile_policy=ProfilePolicy(),
                service=FakeAPIService(error=AnalysisProfileUnavailable()),
                delivery_service=FakeDeliveryService(), metrics=metrics,
                delivery_metrics=delivery_metrics,
            ),
            503,
        )

        transition = AnalysisJobTransitionEvidence(
            snapshot=base.model_copy(
                update={
                    "status": AnalysisJobStatus.CANCEL_REQUESTED,
                    "updated_at": NOW + timedelta(minutes=1),
                }
            ),
            changed=True,
        )
        cancel_session = FakeSession()
        cancel = dbi_analysis_jobs.cancel_analysis_job(
            organization_ref="organization-job-ci", farm_id=FARM_ID, job_id=base.job_id,
            session=cancel_session, context=_context(),
            service=FakeAPIService(transition=transition), metrics=metrics,
        )
        assert cancel.changed and cancel_session.commits == 1

        retry_session = FakeSession()
        retry_delivery = FakeDeliveryService(created=True)
        retry = dbi_analysis_jobs.retry_analysis_job(
            organization_ref="organization-job-ci", farm_id=FARM_ID, job_id=base.job_id,
            session=retry_session, context=_context(), delivery_service=retry_delivery,
            metrics=metrics, delivery_metrics=delivery_metrics,
        )
        assert retry.changed and retry.status is AnalysisJobStatus.QUEUED
        assert retry_session.commits == 1 and retry_delivery.calls == 1
    finally:
        dbi_analysis_jobs._reload_job = original_reload

    job_snapshot = metrics.snapshot()
    assert job_snapshot.create_attempts == 3
    assert job_snapshot.jobs_created == 1
    assert job_snapshot.create_conflicts == 1
    assert job_snapshot.unavailable_profiles == 1
    assert job_snapshot.cancel_attempts == 1 and job_snapshot.cancel_changes == 1
    assert job_snapshot.retry_attempts == 1 and job_snapshot.retry_changes == 1
    assert job_snapshot.rollbacks == 2
    delivery_snapshot = delivery_metrics.snapshot()
    assert delivery_snapshot.enqueue_attempts == 2
    assert delivery_snapshot.messages_created == 2
    assert delivery_snapshot.rollbacks == 1


def validate_metrics_and_boundaries() -> None:
    forbidden_tokens = (
        "tenant", "organization", "farm", "plot", "asset", "job_id",
        "attempt_id", "request_id", "correlation", "principal", "url", "object_key",
    )
    for snapshot_type in (DBIAnalysisJobMetricsSnapshot, DBIDeliveryMetricsSnapshot):
        names = {field.name for field in fields(snapshot_type)}
        assert all(all(token not in name for token in forbidden_tokens) for name in names)

    repository_source = inspect.getsource(DBIAnalysisJobRepository)
    service_source = inspect.getsource(DBIAnalysisJobService)
    api_source = inspect.getsource(dbi_analysis_jobs)
    for source in (repository_source, service_source):
        assert ".commit(" not in source and ".rollback(" not in source
    assert "on_conflict_do_nothing" in repository_source
    assert "with_for_update" in repository_source
    assert 'AnalysisInputAsset.status == "verified"' in repository_source
    assert "DBIPermission.SUBMIT_ANALYSIS" in service_source
    assert "session.commit()" in api_source and "session.rollback()" in api_source
    assert "enqueue_authorized_analysis_command" in api_source
    retry_source = inspect.getsource(dbi_analysis_jobs.retry_analysis_job)
    assert ".retry(" not in retry_source
    for forbidden in (
        "object_key", "bucket", "presigned", "boto3", "requests.",
        "httpx.", "subprocess", "pipeline_orchestrator",
    ):
        assert forbidden not in service_source.lower()


def main() -> None:
    validate_router()
    base = validate_create_replay_and_authorization()
    validate_job_state_machine_compatibility(base)
    validate_api_queue_transaction(base)
    validate_metrics_and_boundaries()
    print("DBI-JOB-003/QUEUE-001 offline aprobado: API atómica y fronteras seguras.")


if __name__ == "__main__":
    main()
