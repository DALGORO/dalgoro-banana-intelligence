"""Valida estáticamente la captura PWA/offline de INSPECT."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps" / "platform-web" / "frontend" / "src"


def _read(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


def validate_route() -> None:
    routes = _read("app/routes.tsx")
    assert "InspectionFieldPage" in routes
    assert (
        "dbi/organizations/:organizationRef/farms/:farmId/plots/:plotId/inspection/new"
        in routes
    )


def validate_stable_offline_identity() -> None:
    field = _read("features/inspectionField.ts")
    offline = _read("features/inspectionOffline.ts")

    assert field.count("crypto.randomUUID()") >= 3
    assert "observationId" in field
    assert "versionId" in field
    assert '"X-DBI-Tenant"' in field
    assert '"X-DBI-Observation-Id"' in field
    assert '"X-DBI-Version-Id"' in field
    assert "inspection_outbox" in offline
    assert "put(action)" in offline
    assert "sendInspectionOutboxAction(syncingAction)" in offline
    assert 'state: "conflict"' in offline

    combined = (field + "\n" + offline).lower()
    for forbidden in (
        "localstorage.getitem(\"token\")",
        "localstorage.getitem('token')",
        "authorization:",
        "bearer ",
        "signed_url",
        "object_key",
        "local_path",
    ):
        assert forbidden not in combined


def validate_truth_ground_ui() -> None:
    page = _read("pages/InspectionFieldPage.tsx")
    assert "Fouré 0–6" in page
    assert "sampling_point_id" in page
    assert "UP ID opcional" in page
    assert "pending_private_upload" in page
    assert 'state: "not_measured"' in page
    assert "GPS observado" in page
    assert "nunca redefine por sí sola la identidad de una UP" in page
    assert "diagnostic: null" in page
    assert "structural: null" in page


def validate_server_contract_transport() -> None:
    field = _read("features/inspectionField.ts")
    assert "field-observations" in field
    request = field.split("export type InspectionCreateRequest", 1)[1].split("};", 1)[0]
    assert "tenant_ref" not in request
    assert "operator_ref" not in field
    assert "recorded_by_ref" not in field


def main() -> None:
    validate_route()
    validate_stable_offline_identity()
    validate_truth_ground_ui()
    validate_server_contract_transport()
    print(
        "DBI-INSPECT-001 PWA aprobada: captura offline, identidad estable y autoridad server-side."
    )


if __name__ == "__main__":
    main()
