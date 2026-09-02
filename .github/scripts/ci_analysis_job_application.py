"""Valida servicio, API e invariantes de DBI-JOB-003 completamente offline."""

from __future__ import annotations

import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

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
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
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
from app.dbi.jobs.state_machine import (  # noqa: E402
    AnalysisJobStatus,
    InvalidAnalysisJobTransition,
)

FARM_ID = UUID("10000000-0000-0000-0000-000000000001")
PLOT_ID = UUID("20000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("30000000-0000-0000-0000-000000000001")
ORTHOPHOTO_ID = UUID("40000000-0000-0000-0000-000000000001")
ORTHOPHOTO_ALT_ID = UUID("40000000-0000-0000-0000-000000000002")
BOUNDARY_ID = UUID("50000000-0000-0000-0000-000000000001")
EXCLUSIONS_ID = UUID("60000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 4, 22, 0, tzinfo=timezone.utc)


def _context(*, submit: bool = True) -> DBIAccessContext:
    permissions = (
        frozenset({DBIPermission.SUBMIT_ANALYSIS})
        if submit
        else frozenset({DBIPermission.READ})
    )
    return DBIAccessContext(
        principal_ref="principal-job-ci",
        tenant_ref="tenant-job-ci",
        organization_refs=frozenset({"organization-job-ci"}),
        farm_scopes=frozenset(
            {
                DBIFarmScope(
                    organization_ref="organization-job-ci",
                    farm_id=FARM_ID,
                )
            }
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="organization-job-ci",
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            }
        ),
        permissions=permissions,
    )


def _request(
    *,
    request_id: str = "request-job-ci",
    orthophoto_asset_id: UUID = ORTHOPHOTO_ID,
) -> AnalysisJobCreateRequest:
    return AnalysisJobCreateRequest(
        request_id=request_id,
        campaign_id=CAMPAIGN_ID,
        orthophoto_asset_id=orthophoto_asset_id,
        boundary_asset_id=BOUNDARY_ID,
        exclusions_asset_id=EXCLUSIONS_ID,
    )


class RecordingProfilePolicy:
    def __init__(self) -> None:
        self.calls: list[AnalysisProfileResolutionContext] = []

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        self.calls.append(context)
        return ApprovedAnalysisProfile(
            model_version_id="banana-density-approved-ci",
            pipeline_config_version="pipeline-approved-ci",
            policy_ref="policy-approved-ci",
        )


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.jobs: dict[tuple[str, str], AnalysisJobSnapshot] = {}
        self.apply_calls = 0
        self.current: AnalysisJobSnapshot | None = None

    def require_plot(self, **kwargs) -> None:
        del kwargs
        self.calls.append("require_plot")

    def require_campaign(self, **kwargs) -> None:
        del kwargs
        self.calls.append("require_campaign")

    def require_verified_asset(self, *, asset_kind: str, **kwargs) -> None:
        del kwargs
        self.calls.append(f"asset:{asset_kind}")

    def get_by_request_for_update(
        self,
        *,
        tenant_ref: str,
        request_id: str,
    ) -> AnalysisJobSnapshot | None:
        self.calls.append("get_by_request")
        return self.jobs.get((tenant_ref, request_id))

    def get_for_update(self, **kwargs) -> AnalysisJobSnapshot | None:
        del kwargs
        self.calls.append("get_for_update")
        return self.current

    def require_same_intent(self, *, existing, incoming) -> None:
        self.calls.append("require_same_intent")
        DBIAnalysisJobRepository.require_same_intent(
            existing=existing,
            incoming=incoming,
        )

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

    def apply_status(
        self,
        *,
        target_status: AnalysisJobStatus,
        changed_at: datetime,
        **kwargs,
    ) -> AnalysisJobSnapshot:
        del kwargs
        self.calls.append("apply_status")
        self.apply_calls += 1
        if self.current is None:
            raise AssertionError("No existe trabajo mutable en el fixture.")
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

    def retry(self, *args, **kwargs):
        del args, kwargs
        if self.error is not None:
            raise self.error
        return self.transition


def _must_http_error(callback, expected_status: int) -> HTTPException:
    try:
        callback()
    except HTTPException as error:
        assert error.status_code == expected_status
        return error
    raise AssertionError(f"Se esperaba HTTP {expected_status}.")


def validate_router_contract() -> None:
    methods = {
        (route.path, method)
        for route in get_api_router().routes
        if route.path.startswith("/dbi/")
        for method in route.methods
    }
    expected = {
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/jobs",
            "POST",
        ),
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/cancel",
            "POST",
        ),
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/retry",
            "POST",
        ),
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}",
            "GET",
        ),
    }
    assert expected.issubset(methods)


def validate_creation_and_idempotency() -> AnalysisJobSnapshot:
    repository = FakeRepository()
    policy = RecordingProfilePolicy()
    service = DBIAnalysisJobService(repository)

    evidence = service.create(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        request=_request(),
        profile_policy=policy,
        accepted_at=NOW,
    )
    assert evidence.created is True
    assert evidence.snapshot.status is AnalysisJobStatus.ACCEPTED
    assert len(evidence.snapshot.command_sha256) == 64
    assert repository.calls[:5] == [
        "require_plot",
        "require_campaign",
        "asset:orthophoto",
        "asset:boundary",
        "asset:exclusions",
    ]
    assert repository.calls[-2:] == ["get_by_request", "persist_accepted"]
    assert len(policy.calls) == 1

    first_id = evidence.snapshot.job_id
    repeated = service.create(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        request=_request(),
        profile_policy=policy,
        accepted_at=NOW + timedelta(seconds=1),
    )
    assert repeated.created is False
    assert repeated.snapshot.job_id == first_id
    assert len(policy.calls) == 1, "Un reintento exacto no debe reinterpretar el perfil."

    try:
        service.create(
            _context(),
            organization_ref="organization-job-ci",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            request=_request(orthophoto_asset_id=ORTHOPHOTO_ALT_ID),
            profile_policy=policy,
            accepted_at=NOW + timedelta(seconds=2),
        )
    except AnalysisJobPersistenceConflict:
        pass
    else:
        raise AssertionError("La misma clave con otra intención debía fallar.")

    return evidence.snapshot


def validate_authorization_precedes_reads() -> None:
    repository = FakeRepository()
    service = DBIAnalysisJobService(repository)
    try:
        service.create(
            _context(submit=False),
            organization_ref="organization-job-ci",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            request=_request(),
            profile_policy=RecordingProfilePolicy(),
            accepted_at=NOW,
        )
    except Exception as error:
        from app.dbi.authorization import DBIAccessDenied

        assert isinstance(error, DBIAccessDenied)
    else:
        raise AssertionError("READ no debe autorizar SUBMIT_ANALYSIS.")
    assert repository.calls == [], "La denegación debe ocurrir antes de toda lectura."


def validate_transitions(base: AnalysisJobSnapshot) -> None:
    repository = FakeRepository()
    service = DBIAnalysisJobService(repository)

    repository.current = base.model_copy(
        update={"status": AnalysisJobStatus.QUEUED}
    )
    canceled = service.cancel(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        job_id=base.job_id,
        changed_at=NOW + timedelta(minutes=1),
    )
    assert canceled.changed is True
    assert canceled.snapshot.status is AnalysisJobStatus.CANCEL_REQUESTED
    assert repository.apply_calls == 1

    repeated = service.cancel(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        job_id=base.job_id,
        changed_at=NOW + timedelta(minutes=2),
    )
    assert repeated.changed is False
    assert repository.apply_calls == 1

    repository.current = base.model_copy(
        update={"status": AnalysisJobStatus.ACCEPTED}
    )
    try:
        service.cancel(
            _context(),
            organization_ref="organization-job-ci",
            farm_id=FARM_ID,
            job_id=base.job_id,
            changed_at=NOW + timedelta(minutes=3),
        )
    except InvalidAnalysisJobTransition:
        pass
    else:
        raise AssertionError("accepted no debe cancelar directamente.")

    repository.current = base.model_copy(
        update={"status": AnalysisJobStatus.FAILED}
    )
    retried = service.retry(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        job_id=base.job_id,
        changed_at=NOW + timedelta(minutes=4),
    )
    assert retried.changed is True
    assert retried.snapshot.status is AnalysisJobStatus.QUEUED

    repeated_retry = service.retry(
        _context(),
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        job_id=base.job_id,
        changed_at=NOW + timedelta(minutes=5),
    )
    assert repeated_retry.changed is False


def validate_transactional_api(base: AnalysisJobSnapshot) -> None:
    creation = AnalysisJobCreationEvidence(snapshot=base, created=True)
    session = FakeSession()
    response = Response()
    result = dbi_analysis_jobs.create_analysis_job(
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        payload=_request(),
        response=response,
        session=session,
        context=_context(),
        profile_policy=RecordingProfilePolicy(),
        service=FakeAPIService(creation=creation),
    )
    assert response.status_code == 201
    assert session.commits == 1 and session.rollbacks == 0
    assert result.job_id == base.job_id
    dumped = result.model_dump(mode="json")
    for forbidden in (
        "command_sha256",
        "requested_by_ref",
        "orthophoto_asset_id",
        "boundary_asset_id",
        "model_version_id",
    ):
        assert forbidden not in dumped

    conflict_session = FakeSession()
    _must_http_error(
        lambda: dbi_analysis_jobs.create_analysis_job(
            organization_ref="organization-job-ci",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            payload=_request(),
            response=Response(),
            session=conflict_session,
            context=_context(),
            profile_policy=RecordingProfilePolicy(),
            service=FakeAPIService(error=AnalysisJobPersistenceConflict()),
        ),
        409,
    )
    assert conflict_session.commits == 0 and conflict_session.rollbacks == 1

    unavailable_session = FakeSession()
    _must_http_error(
        lambda: dbi_analysis_jobs.create_analysis_job(
            organization_ref="organization-job-ci",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            payload=_request(),
            response=Response(),
            session=unavailable_session,
            context=_context(),
            profile_policy=RecordingProfilePolicy(),
            service=FakeAPIService(error=AnalysisProfileUnavailable()),
        ),
        503,
    )
    assert unavailable_session.commits == 0 and unavailable_session.rollbacks == 1

    transition_snapshot = base.model_copy(
        update={
            "status": AnalysisJobStatus.CANCEL_REQUESTED,
            "updated_at": NOW + timedelta(minutes=1),
        }
    )
    transition = AnalysisJobTransitionEvidence(
        snapshot=transition_snapshot,
        changed=True,
    )
    cancel_session = FakeSession()
    cancel_result = dbi_analysis_jobs.cancel_analysis_job(
        organization_ref="organization-job-ci",
        farm_id=FARM_ID,
        job_id=base.job_id,
        session=cancel_session,
        context=_context(),
        service=FakeAPIService(transition=transition),
    )
    assert cancel_result.status is AnalysisJobStatus.CANCEL_REQUESTED
    assert cancel_result.changed is True
    assert cancel_session.commits == 1 and cancel_session.rollbacks == 0


def validate_static_boundaries() -> None:
    repository_source = inspect.getsource(DBIAnalysisJobRepository)
    service_source = inspect.getsource(DBIAnalysisJobService)
    api_source = inspect.getsource(dbi_analysis_jobs)

    for source in (repository_source, service_source):
        assert ".commit(" not in source
        assert ".rollback(" not in source

    assert "on_conflict_do_nothing" in repository_source
    assert "with_for_update" in repository_source
    assert "AnalysisInputAsset.status == \"verified\"" in repository_source
    assert "DBIPermission.SUBMIT_ANALYSIS" in service_source
    assert "session.commit()" in api_source
    assert "session.rollback()" in api_source
    for forbidden in (
        "object_key",
        "bucket",
        "presigned",
        "boto3",
        "requests.",
        "httpx.",
        "subprocess",
        "pipeline_orchestrator",
    ):
        assert forbidden not in service_source.lower()


def main() -> None:
    validate_router_contract()
    base = validate_creation_and_idempotency()
    validate_authorization_precedes_reads()
    validate_transitions(base)
    validate_transactional_api(base)
    validate_static_boundaries()
    print("Servicio y API idempotente de trabajos DBI aprobados offline.")


if __name__ == "__main__":
    main()
