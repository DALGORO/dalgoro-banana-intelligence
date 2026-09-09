"""Barrera mínima de observabilidad Campaign en la pantalla local de Density."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps" / "platform-web" / "frontend" / "src" / "pages" / "DbiDensityPage.tsx"
BACKEND = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_density_local.py"


def main() -> None:
    frontend = FRONTEND.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")

    required_frontend = (
        "campaign_id: string | null;",
        "Campaign DBI:",
        "vínculo técnico activo para este análisis de densidad",
        "trabajo histórico creado antes de la incorporación de Campaign",
        "data.campaign_id",
    )
    for fragment in required_frontend:
        assert fragment in frontend, f"Falta trazabilidad visual Campaign: {fragment}"

    required_backend = (
        "campaign_id: UUID | None = None",
        "campaign_id=job_campaign_id(job)",
    )
    for fragment in required_backend:
        assert fragment in backend, f"Backend Density dejó de exponer Campaign: {fragment}"

    assert "run-full-analysis" in backend
    assert frontend.count("<span>17 etapas</span>") == 1
    print("Density/Campaign UI: trazabilidad visual y compatibilidad histórica aprobadas.")


if __name__ == "__main__":
    main()
