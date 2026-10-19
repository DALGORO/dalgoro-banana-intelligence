"""CI H14/2H-2D/3E: private immutable cleanup observation, no permissions."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-cleanup-observation")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import fake_test_store  # noqa: E402
from ci_dbi_scientific_raster_reservations import req  # noqa: E402
from ci_dbi_scientific_raster_cleanup_dry_run import (  # noqa: E402
    CAMPAIGN, SCOPE, CASES, sample,
)
from app.api.v1.dbi_scientific_raster_cleanup_dry_run import (  # noqa: E402
    ScientificCleanupPlanReceipt,
)
from app.api.v1.dbi_scientific_raster_cleanup_evidence import (  # noqa: E402
    CleanupEvidenceSubmission, record_cleanup_observation,
    _address, _readback, _bytes, _StoredEvidence,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload,
)
from app.dbi.scientific_raster_cleanup_policy import (  # noqa: E402
    build_cleanup_dry_run,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_s3 import DBIS3ObjectStore  # noqa: E402

ctx = SimpleNamespace(tenant_ref=SCOPE.tenant_ref, principal_ref=SCOPE.actor_ref)
payload = ScientificSessionPreparationPayload(
    schema_version="dbi-h14-private-session-preparation-request.v1",
    manifest_sha256=SCOPE.manifest_sha256,
    reservation_sha256=SCOPE.reservation_sha256,
    idempotency_key="h14-evidence-no-executable-token",
)


def candidate(case):
    audit = sample(case)
    plan = build_cleanup_dry_run(audit, scope=SCOPE)
    return ScientificCleanupPlanReceipt(
        schema_version="dbi-h14-postapproval-cleanup-dry-run.v1",
        campaign_id=CAMPAIGN, campaign_status=audit.campaign_status,
        preparation_id=audit.preparation_id, asset_id=audit.asset_id,
        role=audit.role, index=audit.index,
        reconciliation_status=audit.reconciliation_status,
        proposed_action=plan.action, evidence_sha256=plan.evidence_sha256,
        incomplete_upload_count=plan.incomplete_upload_count,
        unexpected_upload_count=plan.unexpected_upload_count,
        manual_review_required=plan.manual_review_required,
        recorded_upload_candidate=plan.candidate_exact_recorded_upload,
        cleanup_authorized=False, cleanup_executed=False,
        evidence_signed=False, evidence_persisted=False,
        ready_for_upload=False, grants_issued=False,
        parts_received=False, file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )


def submission(plan, digest=None):
    return CleanupEvidenceSubmission(
        schema_version="dbi-h14-cleanup-evidence-submission.v1",
        inspection=payload,
        expected_evidence_sha256=digest or plan.evidence_sha256,
    )


def save(store, plan, digest=None):
    response = Response()
    result = record_cleanup_observation(
        SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
        CAMPAIGN, "rgb", "_", submission(plan, digest),
        req(store), response, None, ctx,
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert response.status_code == (201 if result.created else 200)
    return result


def denied(fn, status):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, status, exc.detail)
    else:
        raise AssertionError("Debió rechazar evidencia no autorizada.")


def run():
    store = DBIInMemoryObjectStore()
    flags = {
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }
    first = candidate(CASES[2])
    other = candidate(CASES[1])
    with patch.dict(os.environ, flags), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
        return_value=first,
    ) as preview:
        saved = save(store, first)
        assert saved.created and saved.evidence_persisted
        assert not any((
            saved.evidence_signed, saved.cleanup_authorized,
            saved.cleanup_executed, saved.grants_issued,
            saved.file_received, saved.content_verified, saved.published,
        ))
        assert len(saved.evidence_object_sha256) == 64
        assert saved.evidence_sha256 == first.evidence_sha256
        assert preview.call_count == 1
        again = save(store, first)
        assert not again.created and again.evidence_object_id == saved.evidence_object_id
        assert again.evidence_object_sha256 == saved.evidence_object_sha256

        address = _address(
            ctx, SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", None, first.evidence_sha256,
        )
        assert address.object_id == saved.evidence_object_id
        assert SCOPE.organization_ref not in address.object_key
        with store.open_read(address) as stream:
            raw = stream.read()
        parsed = _StoredEvidence.model_validate_json(raw)
        assert _bytes(parsed) == raw
        assert parsed.actor_ref == SCOPE.actor_ref
        assert parsed.evidence_sha256 == first.evidence_sha256
        assert parsed.proposed_action == "review_exact_recorded_upload"
        assert parsed.review_observation_only
        assert not parsed.cleanup_authorized and not parsed.signed
        assert _readback(store, address, raw).metadata.sha256 == saved.evidence_object_sha256

        denied(lambda: save(store, first, digest="f"*64), 409)
        with patch(
            "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
            return_value=other,
        ):
            denied(lambda: save(store, first), 409)
            alt = save(store, other)
            assert alt.evidence_object_id != saved.evidence_object_id
            assert alt.evidence_sha256 == other.evidence_sha256

        for corrupt in (
            {"cleanup_authorized": True},
            {"cleanup_executed": True},
            {"evidence_signed": True},
            {"evidence_persisted": True},
            {"published": True},
            {"campaign_id": UUID("11000000-0000-4000-8000-000000000099")},
            {"index": "ndvi"},
        ):
            with patch(
                "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
                return_value=first.model_copy(update=corrupt),
            ):
                denied(lambda: save(store, first), 409)

        original_read = store.open_read

        @contextmanager
        def corrupted_read(where):
            if where == address:
                with BytesIO(b"tampered evidence") as stream:
                    yield stream
            else:
                with original_read(where) as stream:
                    yield stream

        with patch.object(store, "open_read", corrupted_read):
            denied(lambda: save(store, first), 409)

        for key in (
            "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
            "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
            "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
        ):
            with patch.dict(os.environ, {key: "0"}):
                denied(lambda: save(store, first), 404)
        from app.api.v1 import get_api_router
        needle = "/scientific-intake/private-raster-cleanup-observations/"
        for env, allowed in (
            ("production", False), ("staging", False), ("", False),
            ("test", True), ("local", True), ("development", True),
        ):
            with patch.dict(os.environ, {"DBI_ENVIRONMENT": env}):
                assert any(needle in route.path for route in get_api_router().routes) is allowed
                if not allowed:
                    denied(lambda: save(store, first), 404)
    # Production resolver refuses the test-only in-memory provider.
    denied(lambda: __import__(
        "app.api.v1.dbi_scientific_manifest_private", fromlist=["_store"]
    )._store(req(store)), 503)
    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_cleanup_evidence.py").read_text()
    assert "preview_scientific_raster_cleanup(" in source
    assert "DBIStorageWriteRequest" in source
    assert "provider.abort(" not in source and "issue_part_access(" not in source
    assert "session.commit(" not in source and "presigned" not in source
    print("H14/2H-2D/3E OK: S3 JSON immutable evidence; no execution authorization.")


if __name__ == "__main__":
    run()
