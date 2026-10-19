"""CI H14/3G: verify independent immutable evidence chain; no writes or grants."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-chain-readonly")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import fake_test_store
from ci_dbi_scientific_raster_reservations import req
from ci_dbi_scientific_raster_cleanup_dry_run import CAMPAIGN, SCOPE, CASES
from ci_dbi_scientific_raster_cleanup_evidence import candidate, save
from ci_dbi_scientific_raster_cleanup_peer_review import (
    SessionProbe, CampaignRow, CampaignRepo, actor, call as review,
)
from app.api.v1.dbi_scientific_raster_cleanup_review_chain import (
    ReviewChainVerificationRequest, verify_cleanup_review_chain,
)
from app.api.v1.dbi_scientific_raster_cleanup_evidence import _address
from app.api.v1.dbi_scientific_raster_cleanup_peer_review import _review_address
from app.dbi.authorization import DBIPermission
from app.dbi.storage_memory import DBIInMemoryObjectStore
from types import SimpleNamespace


FLAGS = {
    "DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED": "1",
    "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED": "1",
    "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
    "DBI_ENVIRONMENT": "test",
}


def call(store, original, reviewed, *, reviewer=None, original_actor=None,
         original_hash=None, review_hash=None, evidence_digest=None):
    who = reviewer or actor()
    session = SessionProbe()
    response = Response()
    payload = ReviewChainVerificationRequest(
        schema_version="dbi-h14-observation-review-chain-request.v1",
        original_actor_ref=original_actor or SCOPE.actor_ref,
        reviewer_actor_ref=who.principal_ref,
        evidence_sha256=evidence_digest or original.evidence_sha256,
        original_object_sha256=original_hash or original.evidence_object_sha256,
        review_object_sha256=review_hash or reviewed.review_object_sha256,
    )
    try:
        result = verify_cleanup_review_chain(
            SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", "_", payload,
            req(store), response, session, who,
        )
    finally:
        enabled = all(os.environ.get(name) == "1" for name in FLAGS if name != "DBI_ENVIRONMENT")
        enabled = enabled and os.environ.get("DBI_ENVIRONMENT", "").lower() in {
            "test", "development", "local",
        }
        assert session.rollbacks == int(enabled), session.rollbacks
        if enabled:
            assert response.headers["Cache-Control"] == "no-store"
    return result


def denied(fn, status):
    try:
        fn()
    except HTTPException as err:
        assert err.status_code == status, (status, err.status_code, err.detail)
    else:
        raise AssertionError("Private evidence chain was unexpectedly accepted.")


def run():
    store = DBIInMemoryObjectStore()
    first = candidate(CASES[2])
    with patch.dict(os.environ, FLAGS), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
        return_value=first,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_peer_review._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_review_chain._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBICampaignRepository",
        CampaignRepo,
    ):
        original = save(store, first)
        reviewed = review(store, original)
        # The new route is strictly read-only, even for authorized operators.
        with patch.object(store, "put", side_effect=AssertionError("No S3 writes allowed")):
            result = call(store, original, reviewed)
            second = call(store, original, reviewed)
        assert result == second
        assert result.snapshot_chain_verified and result.immutable_objects_verified
        assert result.distinct_actors_verified and result.campaign_snapshot_matches
        assert not any((
            result.live_s3_inventory_rechecked, result.cleanup_authorized,
            result.cleanup_executed, result.evidence_signed, result.grants_issued,
            result.file_received, result.content_verified, result.published,
        ))
        assert result.original_object_sha256 == original.evidence_object_sha256
        assert result.review_object_sha256 == reviewed.review_object_sha256
        assert "provider_upload_ref" not in result.model_dump_json()
        denied(lambda: call(store, original, reviewed,
                            original_hash="f" * 64), 409)
        denied(lambda: call(store, original, reviewed,
                            review_hash="f" * 64), 409)
        denied(lambda: call(store, original, reviewed,
                            original_actor="invented-ci-actor"), 404)
        denied(lambda: call(store, original, reviewed,
                            evidence_digest="e" * 64), 404)
        denied(lambda: call(store, original, reviewed,
                            reviewer=actor(SCOPE.actor_ref)), 409)
        denied(lambda: call(store, original, reviewed,
                            reviewer=actor("third-ci-reviewer")), 404)
        denied(lambda: call(store, original, reviewed,
                            reviewer=actor(permission=DBIPermission.READ)), 404)
        denied(lambda: call(store, original, reviewed,
                            reviewer=actor(tenant="foreign")), 404)

        source_address = _address(
            SimpleNamespace(
                tenant_ref=SCOPE.tenant_ref, principal_ref=SCOPE.actor_ref,
            ), SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", None, original.evidence_sha256,
        )
        peer_address = _review_address(
            actor(), SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", None, original.evidence_object_id,
            original.evidence_object_sha256,
        )
        old_read = store.open_read

        @contextmanager
        def corrupt(address):
            if address in {source_address, peer_address}:
                with BytesIO(b"corrupt-private-json") as stream:
                    yield stream
            else:
                with old_read(address) as stream:
                    yield stream

        with patch.object(store, "open_read", corrupt):
            denied(lambda: call(store, original, reviewed), 409)
        CampaignRow.status, CampaignRow.published_at = "PUBLISHED", "published"
        denied(lambda: call(store, original, reviewed), 409)
        CampaignRow.status, CampaignRow.approved_at, CampaignRow.published_at = (
            "TECHNICAL_REVIEW", None, None,
        )
        denied(lambda: call(store, original, reviewed), 404)
        CampaignRow.status, CampaignRow.approved_at = "APPROVED", "approved"

        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-cleanup-review-chain/"
        for env, expected in (
            ("production", False), ("staging", False), ("", False),
            ("test", True), ("local", True), ("development", True),
        ):
            with patch.dict(os.environ, {"DBI_ENVIRONMENT": env}):
                assert any(fragment in r.path for r in get_api_router().routes) is expected
                if not expected:
                    denied(lambda: call(store, original, reviewed), 404)
        for name in FLAGS:
            if name != "DBI_ENVIRONMENT":
                with patch.dict(os.environ, {name: "0"}):
                    denied(lambda: call(store, original, reviewed), 404)

    source = (
        ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_cleanup_review_chain.py"
    ).read_text()
    endpoint = source.split("def verify_cleanup_review_chain(", 1)[1]
    assert endpoint.index("_locked_approved_campaign(") < endpoint.index("_read_json(")
    for forbidden in ("provider.abort(", "issue_part_access(", "session.commit(",
                      "presigned", "initiate_multipart", "cleanup_executed=True"):
        assert forbidden not in source
    print("H14/3G OK: private two-actor chain verified, no S3 refresh/grants/writes.")


if __name__ == "__main__":
    run()
