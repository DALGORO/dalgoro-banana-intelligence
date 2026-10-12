import { useEffect, useRef, useState } from "react";
import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";
import { observedNumberLabel, type INSPECTObservedNumber } from "@/features/inspectionEvidenceRead";

type ApprovedInspection = {
  observed_at: string;
  foure_state: string;
  foure_value: number | null;
  yls_state: string;
  yls_value: number | null;
  functional_leaves_state: string;
  functional_leaves_value: number | null;
};

function readableNumber(state: string, value: number | null): string {
  if (state !== "observed" && state !== "not_measured" && state !== "not_applicable") {
    return "Dato no disponible";
  }
  return observedNumberLabel({
    state,
    value,
    reason: null,
  } as INSPECTObservedNumber);
}

function localDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible" : date.toLocaleString("es-EC");
}

function errorMessage(error: unknown): string {
  const code = (error as { response?: { status?: number } })?.response?.status;
  if (code === 401) return "La sesión expiró. Inicia sesión nuevamente.";
  if (code === 403 || code === 404) {
    return "Esta campaña o su evidencia publicada no está disponible para tu cuenta.";
  }
  if (code === 503) return "La consulta INSPECT no está disponible por el momento.";
  return "No se pudieron consultar las inspecciones aprobadas.";
}

/** Consulta únicamente el DTO público autorizado para una Campaign exacta. */
export function ApprovedInspectionCampaignPanel({
  locator,
  campaignId,
}: {
  locator: PlotMapTimelineLocator;
  campaignId: string | null;
}) {
  const tenantRef = locator.tenantRef;
  const organizationRef = locator.organizationRef;
  const farmId = locator.farmId;
  const plotId = locator.plotId;
  const key = JSON.stringify([tenantRef, organizationRef, farmId, plotId, campaignId]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [result, setResult] = useState<{ key: string; items: ApprovedInspection[] } | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    const current = ++sequence.current;
    setResult(null);
    setError(null);
    setLoading(Boolean(campaignId));
    if (!campaignId) return () => { sequence.current += 1; };

    const url = [
      "/api/v1/dbi/organizations", encodeURIComponent(organizationRef),
      "farms", encodeURIComponent(farmId),
      "plots", encodeURIComponent(plotId),
      "campaigns", encodeURIComponent(campaignId),
      "published-inspections",
    ].join("/");

    api.get<ApprovedInspection[]>(url, {
      headers: { "X-DBI-Tenant": tenantRef },
    }).then(({ data }) => {
      if (sequence.current !== current) return;
      if (!Array.isArray(data)) {
        setError({ key, message: "Respuesta INSPECT no válida." });
        return;
      }
      setResult({ key, items: data });
    }).catch(cause => {
      if (sequence.current === current) {
        setError({ key, message: errorMessage(cause) });
      }
    }).finally(() => {
      if (sequence.current === current) setLoading(false);
    });

    return () => { sequence.current += 1; };
  }, [tenantRef, organizationRef, farmId, plotId, campaignId, key, refreshKey]);

  const entries = result?.key === key ? result.items : null;
  const activeError = error?.key === key ? error.message : null;

  return (
    <section className="dbi-inspect-published space-y-3" aria-label="INSPECT aprobado por campaña">
      <div>
        <h4 className="text-sm font-semibold">Inspecciones de campo aprobadas</h4>
        <p className="muted mt-1 text-xs">
          Sólo resultados de INSPECT con aprobación institucional y vínculo
          científico verificado con la Campaign seleccionada. Sin fotografías,
          GPS, notas privadas ni identificadores técnicos.
        </p>
      </div>
      {!campaignId && (
        <p className="muted text-sm">
          Selecciona una Campaign multiespectral para ver sus inspecciones publicadas.
        </p>
      )}
      {loading && campaignId && <p role="status" aria-live="polite" className="muted text-sm">
        Consultando inspecciones autorizadas…
      </p>}
      {activeError && (
        <div role="alert" className="status-banner status-banner-danger space-y-2">
          <p>{activeError}</p>
          <button type="button" className="btn-secondary"
            onClick={() => setRefreshKey(key => key + 1)}>
            Reintentar consulta
          </button>
        </div>
      )}
      {entries && entries.length === 0 && (
        <p role="status" className="muted text-sm">
          No hay inspecciones publicadas disponibles para esta campaña.
          Esto no demuestra ausencia de visitas ni de problemas en el cultivo.
        </p>
      )}
      {entries && entries.length > 0 && (
        <div className="space-y-3">
          <p role="status" className="text-sm font-semibold">
            {entries.length} {entries.length === 1 ? "inspección aprobada" : "inspecciones aprobadas"}
          </p>
          <ol className="space-y-3">
            {entries.map((item, index) => (
              <li key={index} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-sm font-semibold">Observación de campo · {localDate(item.observed_at)}</p>
                <dl className="dbi-tracking-facts mt-3">
                  <div><dt>Escala Fouré</dt><dd>{readableNumber(item.foure_state, item.foure_value)}</dd></div>
                  <div><dt>YLS</dt><dd>{readableNumber(item.yls_state, item.yls_value)}</dd></div>
                  <div><dt>Hojas funcionales</dt><dd>{readableNumber(item.functional_leaves_state, item.functional_leaves_value)}</dd></div>
                </dl>
              </li>
            ))}
          </ol>
          <p className="muted text-xs">
            Mediciones de campo observadas, no un diagnóstico ni una recomendación automática.
            “No medido” no equivale a cero.
          </p>
        </div>
      )}
    </section>
  );
}
