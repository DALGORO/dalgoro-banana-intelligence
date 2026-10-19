"""CI H14/3H: immutable independent review vs fresh audit; no cleanup rights."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-live-drift")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import fake_test_store
from ci_dbi_scientific_raster_reservations import req
from ci_dbi_scientific_raster_cleanup_dry_run import CAMPAIGN, SCOPE, CASES
from ci_dbi_scientific_raster_cleanup_evidence import candidate, save, payload as inspection
from ci_dbi_scientific_raster_cleanup_peer_review import (
    SessionProbe, CampaignRow, CampaignRepo, actor, call as peer_review,
)
from app.api.v1.dbi_scientific_raster_cleanup_review_chain import ReviewChainVerificationRequest
from app.api.v1.dbi_scientific_raster_reviewed_live_audit import (
    ReviewedLiveAuditRequest, recheck_reviewed_raster_observation,
)
from app.api.v1.dbi_scientific_raster_cleanup_evidence import _address
from app.dbi.authorization import DBIPermission
from app.dbi.storage_memory import DBIInMemoryObjectStore

FLAGS = {
    "DBI_SCIENTIFIC_REVIEWED_LIVE_RECHECK_ENABLED": "1",
    "DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED": "1",
    "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED": "1",
    "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
    "DBI_ENVIRONMENT": "test",
}


def check(store, original, reviewed, *, who=None, original_actor=None,
          reviewer=None, evidence_sha=None, original_sha=None,
          review_sha=None, manifest_sha=None, reservation_sha=None):
    session = SessionProbe()
    response = Response()
    chain = ReviewChainVerificationRequest(
        schema_version="dbi-h14-observation-review-chain-request.v1",
        original_actor_ref=original_actor or SCOPE.actor_ref,
        reviewer_actor_ref=reviewer or "reviewer-ci",
        evidence_sha256=evidence_sha or original.evidence_sha256,
        original_object_sha256=original_sha or original.evidence_object_sha256,
        review_object_sha256=review_sha or reviewed.review_object_sha256,
    )
    inspection_value = inspection
    if manifest_sha or reservation_sha:
        inspection_value = inspection.model_copy(update={
            "manifest_sha256": manifest_sha or inspection.manifest_sha256,
            "reservation_sha256": reservation_sha or inspection.reservation_sha256,
        })
    request_body = ReviewedLiveAuditRequest(
        schema_version="dbi-h14-reviewed-live-audit-request.v1",
        review_chain=chain, inspection=inspection_value,
    )
    try:
        return recheck_reviewed_raster_observation(
            SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id, CAMPAIGN,
            "rgb", "_", request_body, req(store), response,
            session, who or actor(SCOPE.actor_ref),
        )
    finally:
        enabled = (
            all(os.environ.get(flag) == "1" for flag in FLAGS if flag != "DBI_ENVIRONMENT")
            and os.environ.get("DBI_ENVIRONMENT", "").lower() in {"test", "development", "local"}
        )
        assert session.rollbacks == int(enabled)
        assert session.rollbacks <= 1
        assert "Cache-Control" not in response.headers if not enabled else (
            response.headers["Cache-Control"] == "no-store"
        )


def denied(fn, expected):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == expected, (expected, exc.status_code, exc.detail)
    else:
        raise AssertionError("Unsafe live drift recheck accepted.")


def run():
    store = DBIInMemoryObjectStore()
    original_plan = candidate(CASES[2])
    drift_plan = candidate(CASES[1])
    with patch.dict(os.environ, FLAGS), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
        return_value=original_plan,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_peer_review._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reviewed_live_audit._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBICampaignRepository",
        CampaignRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reviewed_live_audit.preview_scientific_raster_cleanup",
        return_value=original_plan,
    ) as live_audit:
        original = save(store, original_plan)
        reviewed = peer_review(store, original)
        with patch.object(store, "put", side_effect=AssertionError("No S3 writes allowed")):
            matched = check(store, original, reviewed)
            again = check(store, original, reviewed)
            assert matched == again
            assert matched.snapshot_matches_live and not matched.evidence_drift_detected
            assert matched.historical_chain_verified and matched.distinct_reviewers_verified
            assert matched.live_s3_inventory_rechecked
            assert matched.separate_nonatomic_read_transactions
            assert matched.manual_review_required
            assert not any((
                matched.cleanup_authorized, matched.cleanup_executed,
                matched.ready_for_upload, matched.grants_issued,
                matched.evidence_signed, matched.file_received,
                matched.content_verified, matched.published,
            ))
            assert matched.baseline_evidence_sha256 == original.evidence_sha256
            assert matched.current_evidence_sha256 == original_plan.evidence_sha256
            assert live_audit.call_count == 2
            call_args = live_audit.call_args.args
            assert call_args[-1].principal_ref == SCOPE.actor_ref
            assert "provider_upload_ref" not in matched.model_dump_json()
            assert "object_key" not in matched.model_dump_json()

            live_audit.return_value = drift_plan
            changed = check(store, original, reviewed)
            assert changed.evidence_drift_detected and not changed.snapshot_matches_live
            assert changed.current_evidence_sha256 == drift_plan.evidence_sha256
            assert changed.current_incomplete_upload_count == 1
            assert changed.current_unexpected_upload_count == 1
            live_audit.return_value = original_plan

            denied(lambda: check(store, original, reviewed,
                                 who=actor()), 409)
            denied(lambda: check(store, original, reviewed,
                                 reviewer=SCOPE.actor_ref), 409)
            denied(lambda: check(store, original, reviewed,
                                 reviewer="stranger"), 404)
            denied(lambda: check(store, original, reviewed,
                                 review_sha="f" * 64), 409)
            denied(lambda: check(store, original, reviewed,
                                 original_sha="f" * 64), 409)
            denied(lambda: check(store, original, reviewed,
                                 evidence_sha="e" * 64), 404)
            denied(lambda: check(store, original, reviewed,
                                 manifest_sha="c" * 64), 409)
            denied(lambda: check(store, original, reviewed,
                                 reservation_sha="d" * 64), 409)
            denied(lambda: check(store, original, reviewed,
                                 who=actor(SCOPE.actor_ref, permission=DBIPermission.READ)), 404)
            denied(lambda: check(store, original, reviewed,
                                 who=actor(SCOPE.actor_ref, tenant="foreign")), 404)

            bad_live = original_plan.model_copy(update={"campaign_status": "PUBLISHED"})
            live_audit.return_value = bad_live
            denied(lambda: check(store, original, reviewed), 409)
            live_audit.return_value = original_plan

            CampaignRow.status, CampaignRow.published_at = "PUBLISHED", "published"
            denied(lambda: check(store, original, reviewed), 409)
            CampaignRow.status, CampaignRow.approved_at, CampaignRow.published_at = (
                "TECHNICAL_REVIEW", None, None,
            )
            denied(lambda: check(store, original, reviewed), 404)
            CampaignRow.status, CampaignRow.approved_at = "APPROVED", "approved"

            from app.dbi.storage_policy import DBIStoragePolicy
            source = _address(
                actor(SCOPE.actor_ref), SCOPE.organization_ref, SCOPE.farm_id,
                SCOPE.plot_id, CAMPAIGN, "rgb", None, original.evidence_sha256,
            )
            real_reader = store.open_read

            @contextmanager
            def corrupted(address):
                if address == source:
                    with BytesIO(b"wrong-archived-evidence") as stream:
                        yield stream
                else:
                    with real_reader(address) as stream:
                        yield stream

            with patch.object(store, "open_read", corrupted):
                denied(lambda: check(store, original, reviewed), 409)

            for name in FLAGS:
                if name != "DBI_ENVIRONMENT":
                    with patch.dict(os.environ, {name: "0"}):
                        denied(lambda: check(store, original, reviewed), 404)
            from app.api.v1 import get_api_router
            fragment = "/scientific-intake/private-raster-reviewed-live-audit/"
            for environment, enabled in (
                ("production", False), ("staging", False), ("", False),
                ("test", True), ("development", True), ("local", True),
            ):
                with patch.dict(os.environ, {"DBI_ENVIRONMENT": environment}):
                    assert any(fragment in r.path for r in get_api_router().routes) is enabled
                    if not enabled:
                        denied(lambda: check(store, original, reviewed), 404)

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_reviewed_live_audit.py").read_text()
    endpoint = source.split("def recheck_reviewed_raster_observation(", 1)[1]
    assert endpoint.index("_locked_approved_campaign(") < endpoint.index("_read_verified_archive(")
    assert endpoint.index("_read_verified_archive(") < endpoint.index("preview_scientific_raster_cleanup(")
    assert "session.commit(" not in source
    for forbidden in ("provider.abort(", "issue_part_access(", "presigned", "cleanup_authorized=True"):
        assert forbidden not in source
    print("H14/3H OK: two-actor immutable review versus current S3; non-atomic/read-only.")


if __name__ == "__main__":
    run()
