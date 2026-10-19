"""CI H14/2H-2D/3D: plan postaprobación conservador y SIN mutaciones."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-cleanup-dry-run-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.api.v1.dbi_scientific_raster_postapproval_audit import (  # noqa: E402
    PostApprovalAuditReceipt,
)
from app.api.v1.dbi_scientific_raster_cleanup_dry_run import (  # noqa: E402
    preview_scientific_raster_cleanup,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload,
)
from app.dbi.scientific_raster_cleanup_policy import (  # noqa: E402
    CleanupPlanEvidenceConflict, build_cleanup_dry_run,
)

CAMPAIGN = UUID("11000000-0000-4000-8000-000000000001")
ASSET = UUID("22000000-0000-4000-8000-000000000002")
PREP = UUID("33000000-0000-4000-8000-000000000003")
CASES = (
    ("no_remote_no_sql", 0, 0, False, False, "none_no_remote_uploads"),
    ("remote_orphan_without_sql", 1, 1, False, False, "investigate_unknown_remote_uploads"),
    ("active_exact_single_upload", 1, 0, True, True, "review_exact_recorded_upload"),
    ("sql_active_remote_missing", 0, 0, False, True, "investigate_missing_recorded_upload"),
    ("sql_active_remote_replaced", 2, 2, False, True, "investigate_unknown_remote_uploads"),
    ("sql_active_remote_extra", 2, 1, True, True, "investigate_unknown_remote_uploads"),
    ("sql_aborted_no_remote", 0, 0, False, True, "none_no_remote_uploads"),
    ("sql_aborted_remote_remains", 1, 1, False, True, "investigate_unknown_remote_uploads"),
)


def sample(case, *, campaign_status="APPROVED", index=None):
    state, count, extra, present, sql, _ = case
    manual = state not in {"no_remote_no_sql", "sql_aborted_no_remote"}
    return PostApprovalAuditReceipt(
        schema_version="dbi-h14-postapproval-readonly-upload-audit.v1",
        campaign_id=CAMPAIGN, campaign_status=campaign_status,
        preparation_id=PREP, asset_id=ASSET,
        role="rgb" if index is None else "scientific_cog",
        index=index, reconciliation_status=state,
        incomplete_upload_count=count, unexpected_upload_count=extra,
        recorded_upload_present=present, sql_start_recorded=sql,
        remote_cleanup_required=count > 0,
        manual_review_required=manual,
        ready_for_upload=False, grants_issued=False, parts_received=False,
        file_received=False, content_verified=False,
        asset_institutionally_approved=False, asset_published=False,
        cleanup_performed=False,
    )


def denied(call, code):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == code, (exc.status_code, code)
    else:
        raise AssertionError("Un plan de limpieza no autorizado fue admitido.")


def run():
    seen = {}
    for case in CASES:
        for campaign_status in ("APPROVED", "PUBLISHED"):
            evidence = sample(case, campaign_status=campaign_status)
            plan = build_cleanup_dry_run(evidence)
            assert plan.action == case[5] and len(plan.evidence_sha256) == 64
            assert plan.incomplete_upload_count == case[1]
            assert plan.unexpected_upload_count == case[2]
            assert plan.candidate_exact_recorded_upload == (case[0] == "active_exact_single_upload")
            assert plan.manual_review_required == evidence.manual_review_required
            assert plan == build_cleanup_dry_run(evidence)
            seen[(campaign_status, case[0])] = plan.evidence_sha256
    assert len(set(seen.values())) == len(seen)

    base = sample(CASES[2])
    for corrupted in (
        {"incomplete_upload_count": 0},
        {"unexpected_upload_count": 1},
        {"recorded_upload_present": False},
        {"sql_start_recorded": False},
        {"manual_review_required": False},
        {"remote_cleanup_required": False},
        {"grants_issued": True},
        {"cleanup_performed": True},
        {"campaign_status": "DRAFT"},
        {"incomplete_upload_count": -1},
        {"incomplete_upload_count": True},
    ):
        try:
            build_cleanup_dry_run(base.model_copy(update=corrupted))
        except CleanupPlanEvidenceConflict:
            pass
        else:
            raise AssertionError(f"Inconsistent audit accepted: {corrupted}")

    flags = {
        "DBI_ENVIRONMENT": "test",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
    }
    payload = ScientificSessionPreparationPayload(
        schema_version="dbi-h14-private-session-preparation-request.v1",
        manifest_sha256="a" * 64, reservation_sha256="b" * 64,
        idempotency_key="ci-only-h14-cleanup-plan-test-key",
    )

    def preview():
        response = Response()
        answer = preview_scientific_raster_cleanup(
            "organization-ci", UUID("44000000-0000-4000-8000-000000000004"),
            UUID("55000000-0000-4000-8000-000000000005"),
            CAMPAIGN, "rgb", "_", payload, SimpleNamespace(), response, None, None,
        )
        assert response.headers["Cache-Control"] == "no-store"
        assert not any((
            answer.cleanup_authorized, answer.cleanup_executed, answer.evidence_signed,
            answer.evidence_persisted, answer.ready_for_upload, answer.grants_issued,
            answer.parts_received, answer.file_received, answer.content_verified,
            answer.institutional_approved, answer.published,
        ))
        assert "upload_ref" not in answer.model_dump_json()
        assert "object_key" not in answer.model_dump_json()
        return answer

    with patch.dict(os.environ, flags), patch(
        "app.api.v1.dbi_scientific_raster_cleanup_dry_run.audit_postapproval_incomplete_raster_uploads",
        return_value=base,
    ) as trusted_audit:
        plan = preview()
        assert plan.proposed_action == "review_exact_recorded_upload"
        assert plan.recorded_upload_candidate
        assert plan.evidence_sha256 == build_cleanup_dry_run(base).evidence_sha256
        assert trusted_audit.call_count == 1
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "0"}):
            denied(preview, 404)
        with patch.dict(os.environ, {"DBI_ENVIRONMENT": "production"}):
            denied(preview, 404)
        with patch.dict(os.environ, {"DBI_ENVIRONMENT": "staging"}):
            denied(preview, 404)
        assert trusted_audit.call_count == 1
        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-cleanup-dry-run/"
        for env, available in (("production", False), ("staging", False),
                               ("", False), ("test", True),
                               ("development", True), ("local", True)):
            with patch.dict(os.environ, {"DBI_ENVIRONMENT": env}):
                assert any(fragment in route.path for route in get_api_router().routes) is available

    # Audit flag is independent: if absent the authoritative audit must
    # fail-closed. Never replace it with client-submitted diagnosis.
    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "0",
        "DBI_ENVIRONMENT": "test",
    }):
        denied(preview, 404)

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_cleanup_dry_run.py").read_text()
    assert "audit_postapproval_incomplete_raster_uploads(" in source
    assert "build_cleanup_dry_run(audit)" in source
    assert "session.commit(" not in source and "provider.abort(" not in source
    assert "issue_part_access(" not in source and "presigned" not in source
    print("H14/2H-2D/3D OK: 8 estados x 2 Campaign, sin abortos, grants ni escrituras.")


if __name__ == "__main__":
    run()
