import { useEffect, useState } from "react";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";
import {
  listMultispectralExtractions, multispectralScopeKey,
  type MultispectralExtraction, type MultispectralSummary,
} from "@/features/multispectralEvidence";

type Result = { scopeKey: string; items: MultispectralExtraction[]; error: string | null };

const INDEX_LABELS: Record<string, string> = {
  ndvi: "NDVI", ndre: "NDRE", gndvi: "GNDVI", evi2: "EVI2",
  ci_red_edge: "CI Red Edge", ci_green: "CI Green",
};
const BAND_LABELS: Record<string, string> = {
  green: "Verde", red: "Rojo", red_edge: "Borde rojo", nir: "Infrarrojo cercano",
};

function number(value: number | null, digits = 3): string {
  return value === null || !Number.isFinite(value)
    ? "Sin píxeles válidos"
    : value.toLocaleString("es-EC", { maximumFractionDigits: digits });
}

function date(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Fecha no disponible"
    : parsed.toLocaleString("es-EC");
}

function errorMessage(error: unknown): string {
  const code = (error as { response?: { status?: number } })?.response?.status;
  if (code === 401) return "La sesión expiró. Inicia sesión nuevamente.";
  if (code === 403 || code === 404) return "No se pueden consultar las extracciones de este lote.";
  if (code === 409) return "La evidencia almacenada no supera la verificación de integridad.";
  if (code === 503) return "La información científica no está disponible en este momento.";
  return "No se pudieron consultar las extracciones. Intenta nuevamente.";
}

function Statistics({ items, heading }: { items: MultispectralSummary[]; heading: string }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold">{heading}</h4>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-left text-xs">
          <thead>
            <tr className="border-b text-slate-600 dark:text-slate-300">
              <th scope="col" className="py-2 pr-3">Variable</th>
              <th scope="col" className="py-2 pr-3">Mediana</th>
              <th scope="col" className="py-2 pr-3">P10–P90</th>
              <th scope="col" className="py-2 pr-3">Píxeles válidos</th>
              <th scope="col" className="py-2">Versión / fuente</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.variable_ref} className="border-b border-slate-200/70 dark:border-slate-700">
                <th scope="row" className="py-2 pr-3 font-medium">
                  {item.variable_kind === "index"
                    ? (INDEX_LABELS[item.variable_ref] ?? item.variable_ref)
                    : (BAND_LABELS[item.variable_ref] ?? item.variable_ref)}
                </th>
                <td className="py-2 pr-3">{number(item.median)}</td>
                <td className="py-2 pr-3">{item.p10 === null || item.p90 === null
                  ? "—" : `${number(item.p10)} – ${number(item.p90)}`}</td>
                <td className="py-2 pr-3">
                  {item.valid_count}/{item.selected_count}
                  {" "}({number(item.valid_fraction * 100, 1)}%)
                </td>
                <td className="py-2">{item.formula_version
                  ?? (item.source_ref ? "Banda fuente trazable" : "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Consulta bajo READ, sin IndexedDB/localStorage ni enlaces a objetos originales. */
export function MultispectralEvidencePanel({ locator }: { locator: PlotMapTimelineLocator }) {
  const scopeKey = multispectralScopeKey(locator);
  const [result, setResult] = useState<Result | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    listMultispectralExtractions(locator)
      .then(items => { if (active) setResult({ scopeKey, items, error: null }); })
      .catch(error => {
        if (active) setResult({ scopeKey, items: [], error: errorMessage(error) });
      });
    return () => { active = false; };
  }, [locator, scopeKey, refresh]);

  // Nunca mostrar resultados de otro tenant/lote durante navegación o recarga.
  const current = result?.scopeKey === scopeKey ? result : null;
  const items = current?.items ?? [];
  const selected = items.find(item => item.extraction_id === selectedId) ?? items[0];
  const payload = selected?.payload;
  return (
    <section className="card space-y-4" aria-label="Evidencia multiespectral">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="eyebrow">Multiespectral · evidencia derivada</div>
          <h2 className="mt-1 text-lg font-semibold">Bandas e índices del lote</h2>
          <p className="muted mt-1 text-sm">
            Estadísticas científicas vinculadas a una observación de campo.
            No constituyen un diagnóstico de Sigatoka ni una recomendación de tratamiento.
          </p>
        </div>
        <button type="button" className="btn-secondary"
          onClick={() => { setResult(null); setRefresh(value => value + 1); }}>
          Actualizar evidencia
        </button>
      </div>

      {!current && <p role="status" className="muted text-sm">Consultando extracciones autorizadas…</p>}
      {current?.error && <p role="alert" className="status-banner status-banner-danger">{current.error}</p>}
      {current && !current.error && items.length === 0 && (
        <p className="muted text-sm">
          Este lote todavía no tiene extracciones multiespectrales derivadas disponibles.
          Se mostrarán únicamente cuando existan datos científicos persistidos y autorizados.
        </p>
      )}
      {selected && payload && (
        <div className="space-y-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="text-sm font-medium" htmlFor="multi-extraction-select">
              Extracciones recientes por fecha de registro (máximo 20)
            </label>
            <select id="multi-extraction-select" className="w-full sm:max-w-lg"
              value={selected.extraction_id}
              onChange={event => setSelectedId(event.target.value)}>
              {items.map(item => (
                <option key={item.extraction_id} value={item.extraction_id}>
                  Campo: {date(item.observed_at)} · Registro: {date(item.created_at)} · {item.payload.support_mode === "copa_up" ? "Copa UP" : "Ventana"} · {item.extraction_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>

          <p className="muted text-xs">
            Fecha INSPECT = observación de campo; registro = cálculo persistido.
            La fecha de vuelo solo se muestra cuando existe una cadena de procedencia verificada
            entre el ráster científico, su artefacto, el trabajo y Campaign.
            No se comparan vuelos automáticamente.
          </p>
          <dl className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
            <div><dt className="muted">Observación de campo (INSPECT)</dt>
              <dd className="mt-1 font-medium">{date(selected.observed_at)}</dd></div>
            <div><dt className="muted">Registro de la extracción</dt>
              <dd className="mt-1 font-medium">{date(selected.created_at)}</dd></div>
            <div><dt className="muted">Campaign / levantamiento</dt>
              <dd className="mt-1 font-medium">{selected.campaign_linkage === "verified_job_chain"
                && selected.campaign_id ? selected.campaign_id : "Campaña no verificada"}</dd></div>
            <div><dt className="muted">Captura del vuelo</dt>
              <dd className="mt-1 font-medium">{selected.campaign_linkage === "verified_job_chain"
                && selected.captured_at ? date(selected.captured_at) : "Fecha de vuelo no verificada"}</dd></div>
            <div><dt className="muted">Tipo de evidencia</dt>
              <dd className="mt-1 font-medium">Derivada · no observada ni inferida</dd></div>
            <div><dt className="muted">Soporte espacial</dt>
              <dd className="mt-1 font-medium">{payload.support_mode === "copa_up"
                ? "Follaje atribuible a UP" : "Ventana sustituta"}</dd></div>
            <div><dt className="muted">Píxeles seleccionados</dt>
              <dd className="mt-1 font-medium">{payload.selected_count}</dd></div>
            <div><dt className="muted">Versión INSPECT observada</dt>
              <dd className="mt-1 break-all font-medium">{payload.observation_version_id}</dd></div>
            <div><dt className="muted">Producto ráster científico</dt>
              <dd className="mt-1 break-all font-medium">{payload.source_raster_product_id}</dd></div>
            <div><dt className="muted">Perfil de soporte</dt>
              <dd className="mt-1 break-all font-medium">{payload.support_profile_version}</dd></div>
          </dl>
          {payload.support_limitation && (
            <p className="rounded-xl border border-amber-300/60 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-600/50 dark:bg-amber-950/20 dark:text-amber-200">
              <strong>Limitación espacial:</strong> {payload.support_limitation}
            </p>
          )}
          <p className="muted text-xs">
            Los índices dependen de bandas, calibración y píxeles válidos; sus cifras
            no se deben comparar directamente entre vuelos sin verificar compatibilidad.
          </p>
          <Statistics heading="Índices derivados" items={payload.summaries.filter(item => item.variable_kind === "index")} />
          <Statistics heading="Bandas fuente resumidas" items={payload.summaries.filter(item => item.variable_kind === "band")} />
        </div>
      )}
    </section>
  );
}
