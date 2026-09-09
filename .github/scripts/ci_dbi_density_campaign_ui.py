"""Barrera mínima de observabilidad Campaign en la pantalla local de Density."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps" / "platform-web" / "frontend" / "src" / "pages" / "DbiDensityPage.tsx"
WRAPPER = ROOT / "apps" / "platform-web" / "frontend" / "src" / "pages" / "DbiDensityWithCandidateReview.tsx"
BACKEND = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_density_local.py"
ADOPTION_API = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_density_legacy_campaign.py"
ADOPTION_SERVICE = ROOT / "apps" / "platform-web" / "backend" / "app" / "dbi" / "density_legacy_campaign.py"
BRIDGE = ROOT / "services" / "banana-density" / "web_bridge.py"


def main() -> None:
    frontend = FRONTEND.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")
    adoption_api = ADOPTION_API.read_text(encoding="utf-8")
    adoption_service = ADOPTION_SERVICE.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")

    required_frontend = (
        "campaign_id: string | null;",
        "Campaign DBI:",
        "vínculo técnico activo para este análisis de densidad",
        "trabajo histórico creado antes de la incorporación de Campaign",
        "data.campaign_id",
    )
    for fragment in required_frontend:
        assert fragment in frontend, f"Falta trazabilidad visual Campaign: {fragment}"

    required_wrapper = (
        "Adoptar trabajo histórico en Campaign",
        "sin volver a ejecutar YOLO ni ninguna de las 17 etapas científicas",
        "/campaign-adoption",
        "Trabajo histórico adoptado",
        "Catálogo técnico:",
        'key={`${job?.job_id ?? "none"}:${job?.campaign_id ?? "historical"}`}',
    )
    for fragment in required_wrapper:
        assert fragment in wrapper, f"Falta adopción histórica visible: {fragment}"

    required_backend = (
        "campaign_id: UUID | None = None",
        "campaign_id=job_campaign_id(job)",
    )
    for fragment in required_backend:
        assert fragment in backend, f"Backend Density dejó de exponer Campaign: {fragment}"

    for fragment in (
        '"/companies/{company_id}/density/jobs/{job_id}/campaign-adoption"',
        "adopt_historical_density_job_to_campaign",
        "DBICampaignArtifactType.ORTHOPHOTO_SOURCE",
        "CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK",
        "campaign_origin=LEGACY_CAMPAIGN_ORIGIN",
    ):
        assert fragment in adoption_api, f"Falta contrato de adopción histórica: {fragment}"

    assert "uuid5(" in adoption_service
    assert 'LEGACY_CAMPAIGN_ORIGIN = "legacy_import"' in adoption_service
    assert "DBICampaignStatus.ANALYZED" in adoption_service
    assert "run-full-analysis" in backend
    assert frontend.count("<span>17 etapas</span>") == 1
    assert "campaign" not in bridge.casefold()
    print("Density/Campaign UI: trazabilidad, adopción histórica y aislamiento científico aprobados.")


if __name__ == "__main__":
    main()