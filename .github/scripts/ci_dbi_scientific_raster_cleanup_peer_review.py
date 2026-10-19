"""CI H14/2H-2D/3F: segundo revisor con MANAGE, evidencia S3 inmutable."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-two-actor-review-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import fake_test_store  # noqa: E402
from ci_dbi_scientific_raster_reservations import req  # noqa: E402
from ci_dbi_scientific_raster_cleanup_dry_run import CAMPAIGN, SCOPE, CASES  # noqa: E402
from ci_dbi_scientific_raster_cleanup_evidence import (  # noqa: E402
    candidate, save,
)
from app.api.v1.dbi_scientific_raster_cleanup_peer_review import (  # noqa: E402
    IndependentReviewSubmission, record_independent_review,
    _review_address, _StoredIndependentReview, _canonical,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402


class SessionProbe:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        raise AssertionError("No SQL writes/commits permitted")

    def add(self, *args):
        raise AssertionError("No SQL writes permitted")


class CampaignRow:
    status = "APPROVED"
    approved_at = "approved"
    published_at = None


class CampaignRepo:
    def __init__(self, session):
        assert isinstance(session, SessionProbe)

    def get_campaign_for_update(self, **kwargs):
        assert kwargs["campaign_id"] == CAMPAIGN
        return SimpleNamespace(
            id=CAMPAIGN,
            tenant_ref=SCOPE.tenant_ref,
            organization_ref=SCOPE.organization_ref,
            farm_id=SCOPE.farm_id,
            plot_id=SCOPE.plot_id,
            analysis_type="multispectral",
            status=CampaignRow.status,
            approved_at=CampaignRow.approved_at,
            published_at=CampaignRow.published_at,
        )


def actor(ref="reviewer-ci", permission=DBIPermission.MANAGE, tenant=None):
    return DBIAccessContext(
        principal_ref=ref,
        tenant_ref=tenant or SCOPE.tenant_ref,
        organization_refs=frozenset({SCOPE.organization_ref}),
        farm_scopes=frozenset({DBIFarmScope(SCOPE.organization_ref, SCOPE.farm_id)}),
        plot_scopes=frozenset({
            DBIPlotScope(SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id)
        }),
        permissions=frozenset({permission}),
    )


def call(store, original, *, reviewer=None, original_actor=None,
         evidence_digest=None, original_hash=None):
    response = Response()
    session = SessionProbe()
    payload = IndependentReviewSubmission(
        schema_version="dbi-h14-independent-observation-review-request.v1",
        original_actor_ref=original_actor or SCOPE.actor_ref,
        evidence_sha256=evidence_digest or original.evidence_sha256,
        original_object_sha256=original_hash or original.evidence_object_sha256,
        acknowledgement="reviewed_snapshot_not_cleanup_authorization",
    )
    try:
        result = record_independent_review(
            SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", "_", payload,
            req(store), response, session, reviewer or actor(),
        )
    finally:
        gate_open = (
            all(os.environ.get(flag) == "1" for flag in (
                "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED",
                "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
                "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
                "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
            ))
            and os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
            in {"test", "development", "local"}
        )
        # Feature gate 404 never opened SQL; guarded operations release lock.
        assert session.rollbacks == int(gate_open)
        if gate_open:
            assert response.headers["Cache-Control"] == "no-store"
        else:
            assert "Cache-Control" not in response.headers
    assert response.status_code == (201 if result.created else 200)
    return result


def denied(fn, code):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == code, (code, exc.status_code, exc.detail)
    else:
        raise AssertionError("Unsafe peer review unexpectedly accepted")


def run():
    store = DBIInMemoryObjectStore()
    first = candidate(CASES[2])
    flags = {
        "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED": "1",
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }
    with patch.dict(os.environ, flags), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_evidence.preview_scientific_raster_cleanup",
        return_value=first,
    ), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_peer_review._private_s3_store",
        fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBICampaignRepository",
        CampaignRepo,
    ):
        original = save(store, first)
        result = call(store, original)
        assert result.created and result.review_recorded and result.independent_actor
        assert result.snapshot_only
        assert result.original_object_sha256 == original.evidence_object_sha256
        assert not any((result.evidence_signed, result.cleanup_authorized,
                        result.cleanup_executed, result.grants_issued,
                        result.file_received, result.content_verified, result.published))
        again = call(store, original)
        assert not again.created
        assert again.review_object_id == result.review_object_id
        reviewer = actor()
        address = _review_address(
            reviewer, SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", None,
            original.evidence_object_id, original.evidence_object_sha256,
        )
        assert address.object_id == result.review_object_id
        assert SCOPE.organization_ref not in address.object_key
        with store.open_read(address) as stream:
            raw = stream.read()
        saved = _StoredIndependentReview.model_validate_json(raw)
        assert _canonical(saved) == raw
        assert saved.original_actor_ref == SCOPE.actor_ref
        assert saved.reviewer_actor_ref == reviewer.principal_ref
        assert saved.campaign_id == CAMPAIGN
        assert not saved.cleanup_authorized and not saved.evidence_signed

        third = call(store, original, reviewer=actor("another-reviewer"))
        assert third.created and third.review_object_id != result.review_object_id

        denied(lambda: call(store, original, reviewer=actor(SCOPE.actor_ref)), 409)
        denied(lambda: call(store, original, reviewer=actor(
            permission=DBIPermission.READ,
        )), 404)
        denied(lambda: call(store, original, reviewer=actor(tenant="foreign")), 404)
        denied(lambda: call(store, original, original_actor="invented-actor"), 404)
        denied(lambda: call(store, original, evidence_digest="e" * 64), 404)
        denied(lambda: call(store, original, original_hash="f" * 64), 409)

        CampaignRow.status, CampaignRow.published_at = "PUBLISHED", "published"
        denied(lambda: call(store, original), 409)  # old APPROVED snapshot
        CampaignRow.status, CampaignRow.published_at = "TECHNICAL_REVIEW", None
        CampaignRow.approved_at = None
        denied(lambda: call(store, original), 404)
        CampaignRow.status, CampaignRow.approved_at = "APPROVED", "approved"

        original_read = store.open_read
        from app.api.v1.dbi_scientific_raster_cleanup_evidence import _address
        source_address = _address(
            SimpleNamespace(
                tenant_ref=SCOPE.tenant_ref, principal_ref=SCOPE.actor_ref,
            ), SCOPE.organization_ref, SCOPE.farm_id, SCOPE.plot_id,
            CAMPAIGN, "rgb", None, original.evidence_sha256,
        )

        @contextmanager
        def corrupt(where):
            if where == source_address:
                with BytesIO(b"tampered evidence") as stream:
                    yield stream
            else:
                with original_read(where) as stream:
                    yield stream

        with patch.object(store, "open_read", corrupt):
            denied(lambda: call(store, original), 409)

        for name in flags:
            if name == "DBI_ENVIRONMENT":
                continue
            with patch.dict(os.environ, {name: "0"}):
                denied(lambda: call(store, original), 404)

        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-cleanup-peer-review/"
        for env, enabled in (
            ("production", False), ("staging", False), ("", False),
            ("local", True), ("development", True), ("test", True),
        ):
            with patch.dict(os.environ, {"DBI_ENVIRONMENT": env}):
                found = any(fragment in route.path for route in get_api_router().routes)
                assert found is enabled, (env, found)
                if not enabled:
                    denied(lambda: call(store, original), 404)

    # Real resolver rejects memory provider; no fallback to local.
    from app.api.v1.dbi_scientific_manifest_private import _store as production_store
    denied(lambda: production_store(req(store)), 503)
    content = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_cleanup_peer_review.py").read_text()
    assert "provider.abort(" not in content
    assert "issue_part_access(" not in content
    assert "session.commit(" not in content
    assert "presigned" not in content
    print("H14/2H-2D/3F OK: two distinct MANAGE actors; immutable snapshot review; no cleanup rights.")


if __name__ == "__main__":
    run()
