from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps" / "platform-web" / "frontend"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(text: str, needle: str, *, source: str) -> None:
    if needle not in text:
        raise AssertionError(f"{source}: falta marcador obligatorio {needle!r}")


def forbid(text: str, needle: str, *, source: str) -> None:
    if needle.lower() in text.lower():
        raise AssertionError(f"{source}: contenido prohibido {needle!r}")


def main() -> None:
    manifest_path = FRONTEND / "public" / "manifest.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["icons"] and manifest["icons"][0]["src"] == "/pwa-icon.svg"

    service_worker = read("apps/platform-web/frontend/public/dbi-sw.js")
    require(service_worker, 'url.pathname.startsWith("/api")', source="dbi-sw.js")
    require(service_worker, 'request.method !== "GET"', source="dbi-sw.js")
    require(service_worker, "SHELL_CACHE", source="dbi-sw.js")
    for forbidden in (
        "authorization",
        "bearer",
        "document.cookie",
        "localstorage",
        "indexeddb",
        "signed_url",
        "presigned",
    ):
        forbid(service_worker, forbidden, source="dbi-sw.js")

    index_html = read("apps/platform-web/frontend/index.html")
    require(index_html, 'rel="manifest" href="/manifest.webmanifest"', source="index.html")
    require(index_html, 'name="theme-color"', source="index.html")

    main_tsx = read("apps/platform-web/frontend/src/main.tsx")
    require(main_tsx, "serviceWorker.register('/dbi-sw.js')", source="main.tsx")
    require(main_tsx, "import.meta.env.PROD", source="main.tsx")

    routes = read("apps/platform-web/frontend/src/app/routes.tsx")
    require(routes, "SamplingFieldPage", source="routes.tsx")
    require(
        routes,
        "dbi/organizations/:organizationRef/farms/:farmId/plots/:plotId/sampling/:planId",
        source="routes.tsx",
    )

    sampling = read("apps/platform-web/frontend/src/features/samplingField.ts")
    require(sampling, "/api/v1/dbi/organizations", source="samplingField.ts")
    require(sampling, "/validate", source="samplingField.ts")
    require(sampling, "/reject", source="samplingField.ts")
    require(sampling, "/substitute", source="samplingField.ts")
    require(sampling, "planned_longitude", source="samplingField.ts")
    require(sampling, "observed_longitude", source="samplingField.ts")

    offline = read("apps/platform-web/frontend/src/features/samplingOffline.ts")
    require(offline, 'DB_NAME = "dbi-field-pwa-v1"', source="samplingOffline.ts")
    require(offline, 'PLAN_STORE = "sampling_plans"', source="samplingOffline.ts")
    require(offline, 'OUTBOX_STORE = "sampling_outbox"', source="samplingOffline.ts")
    for state in ("pending", "syncing", "conflict", "auth_required", "failed"):
        require(offline, state, source="samplingOffline.ts")
    forbid(offline, "bearer", source="samplingOffline.ts")
    forbid(offline, "authorization", source="samplingOffline.ts")

    page = read("apps/platform-web/frontend/src/pages/SamplingFieldPage.tsx")
    require(page, "navigator.geolocation", source="SamplingFieldPage.tsx")
    require(page, "maplibre-gl", source="SamplingFieldPage.tsx")
    require(page, "Modo offline", source="SamplingFieldPage.tsx")
    require(page, "primary", source="SamplingFieldPage.tsx")
    require(page, "reserve", source="SamplingFieldPage.tsx")
    require(page, "Sincronizar", source="SamplingFieldPage.tsx")
    for out_of_scope in ("Fouré", "YLS", "nematod", "pseudotallo", "lesión"):
        forbid(page, out_of_scope, source="SamplingFieldPage.tsx")

    print("DBI-PWA-001: contrato estático PWA/offline verificado correctamente.")


if __name__ == "__main__":
    main()
