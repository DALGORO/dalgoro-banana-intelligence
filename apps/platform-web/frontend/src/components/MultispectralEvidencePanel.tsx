import { useEffect, useState } from "react";
import { Layers3, ShieldCheck } from "lucide-react";
import { coverageLabel, INDEX_EXPLANATIONS } from "@/features/producerEvidenceReadout";
import { extractionForMapCampaign, verifiedMultispectralCampaigns } from "@/features/multispectralCampaignHistory";
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
export function MultispectralEvidencePanel({
  locator, selectedMapDate, selectedMapCampaignId,
  onChooseVerifiedCampaign, onClearMapSelection,
}: {
  locator: PlotMapTimelineLocator;
  selectedMapDate: string;
  selectedMapCampaignId: string | null;
  onChooseVerifiedCampaign: (campaignId: string, capturedAt: string) => void;
  onClearMapSelection: () => void;
}) {
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
  const verifiedHistory = verifiedMultispectralCampaigns(items, locator);
  const selected = extractionForMapCampaign(
    items, locator, selectedMapDate, selectedMapCampaignId, selectedId,
  );
  const payload = selected?.payload;
  const verifiedFlight = Boolean(
    selected?.campaign_linkage === "verified_job_chain"
    && selected.campaign_id && selected.captured_at
    && verifiedHistory.some(entry => entry.campaignId === selected.campaign_id
      && Date.parse(entry.capturedAt) === Date.parse(selected.captured_at!)),
  );
  return (
    <section id="dbi-multi-evidence" className="card dbi-multi-panel space-y-4" aria-label="Evidencia multiespectral">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className="dbi-section-icon" aria-hidden="true"><Layers3 size={22} /></span>
          <div className="min-w-0">
          <div className="eyebrow">Multiespectral · evidencia derivada</div>
          <h2 className="mt-1 text-lg font-semibold">Bandas e índices del lote</h2>
          <p className="muted mt-1 text-sm">
            Estadísticas científicas vinculadas a una observación de campo.
            No constituyen un diagnóstico de Sigatoka ni una recomendación de tratamiento.
          </p>
          </div>
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
      {current && !current.error && items.length > 0 && (
        <section className="space-y-2" aria-label="Historial de vuelos multiespectrales verificados">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Vuelos multiespectrales verificados</h3>
            <span className="muted text-xs">{verifiedHistory.length} campañas verificadas · máximo 20 extracciones revisadas</span>
          </div>
          {verifiedHistory.length === 0 ? (
            <p className="muted rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700">
              Todavía no hay vuelos con procedencia científica verificada para este lote.
              Las extracciones sin vínculo siguen disponibles en el selector inferior.
            </p>
          ) : (
            <div className="dbi-campaign-strip" role="group" aria-label="Elegir vuelo verificado">
              {verifiedHistory.map((entry, index) => {
                const active = selected?.campaign_linkage === "verified_job_chain"
                  && selected.campaign_id === entry.campaignId;
                return (
                  <button key={entry.campaignId} type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setSelectedId(entry.latestExtractionId);
                      onChooseVerifiedCampaign(entry.campaignId, entry.capturedAt);
                    }}
                    className={`rounded-xl border px-3 py-2 text-left text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600 ${
                      active
                        ? "border-emerald-600 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/30 dark:text-emerald-100"
                        : "border-slate-200 hover:border-emerald-500 dark:border-slate-700"
                    }`}>
                    <span className="block font-semibold">Vuelo {index + 1}</span>
                    <span className="block text-xs">{date(entry.capturedAt)}</span>
                    <span className="block text-xs opacity-75">
                      {entry.extractionCount} {entry.extractionCount === 1 ? "muestra analizada" : "muestras analizadas"}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          <p className="muted text-xs">
            Este historial permite consultar campañas acreditadas, no comparar resultados entre vuelos.
            La comparabilidad de calibración, unidades espaciales y fórmulas sigue pendiente de validación.
          </p>
        </section>
      )}
      {current && !current.error && items.length > 0 && selectedMapDate && !selected && (
        <p role="status" className="rounded-xl border border-amber-300/60 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-600/50 dark:bg-amber-950/20 dark:text-amber-200">
          La fecha seleccionada en el mapa no identifica un único vuelo multiespectral verificado.
          Selecciona un vuelo concreto en el historial para consultar sus estadísticas,
          o cambia la fecha del mapa. No se muestran cifras de otro levantamiento.
        </p>
      )}
      {selected && payload && (
        <div className="space-y-5">
          <div className="flex items-center gap-2 text-xs font-medium text-emerald-700 dark:text-emerald-300">
            <ShieldCheck size={16} aria-hidden="true" />
            {selected.campaign_linkage === "verified_job_chain" && selected.campaign_id
              && verifiedHistory.some(entry => entry.campaignId === selected.campaign_id)
              ? "Vuelo con procedencia científica verificada"
              : "Análisis disponible · sin vuelo cartográfico verificado"}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="text-sm font-medium" htmlFor="multi-extraction-select">
              Extracciones recientes por fecha de registro (máximo 20)
            </label>
            <select id="multi-extraction-select" className="w-full sm:max-w-lg"
              value={selected.extraction_id}
              onChange={event => {
                const item = items.find(row => row.extraction_id === event.target.value);
                if (!item) return;
                setSelectedId(item.extraction_id);
                if (item.campaign_linkage === "verified_job_chain"
                  && item.campaign_id && item.captured_at
                  && verifiedHistory.some(row => row.campaignId === item.campaign_id
                    && Date.parse(row.capturedAt) === Date.parse(item.captured_at!))) {
                  onChooseVerifiedCampaign(item.campaign_id, item.captured_at);
                } else {
                  onClearMapSelection();
                }
              }}>
              {items.map((item, index) => (
                <option key={item.extraction_id} value={item.extraction_id}>
                  Muestra {index + 1} · Campo: {date(item.observed_at)} · Registro: {date(item.created_at)} · {item.payload.support_mode === "copa_up" ? "Follaje" : "Ventana"}
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
            <div><dt className="muted">Vinculación con el vuelo</dt>
              <dd className="mt-1 font-medium">{verifiedFlight
                ? "Procedencia del vuelo verificada" : "Vuelo no verificado"}</dd></div>
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
            <div><dt className="muted">Trazabilidad técnica</dt>
              <dd className="mt-1 font-medium">Versión de campo y producto científico vinculados en el sistema</dd></div>
            <div><dt className="muted">Perfil de soporte</dt>
              <dd className="mt-1 break-all font-medium">{payload.support_profile_version}</dd></div>
          </dl>
          {payload.support_limitation && (
            <p className="rounded-xl border border-amber-300/60 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-600/50 dark:bg-amber-950/20 dark:text-amber-200">
              <strong>Limitación espacial:</strong> {payload.support_limitation}
            </p>
          )}
          <section className="dbi-producer-readout space-y-3" aria-label="Lectura rápida para el productor">
            <h3 className="text-sm font-semibold">Lo esencial de este levantamiento</h3>
            <dl className="dbi-producer-facts">
              <div>
                <dt>Observación en campo (INSPECT)</dt>
                <dd>{date(selected.observed_at)}</dd>
              </div>
              <div>
                <dt>Vuelo multiespectral</dt>
                <dd>{verifiedFlight && selected.captured_at
                  ? date(selected.captured_at) : "Fecha de vuelo no verificada"}</dd>
              </div>
              <div>
                <dt>Variables registradas en la extracción</dt>
                <dd>{payload.summaries.filter(item => item.variable_kind === "index").length} índices
                  {" · "}{payload.summaries.filter(item => item.variable_kind === "band").length} bandas</dd>
              </div>
              <div>
                <dt>Soporte espacial de la muestra</dt>
                <dd>{payload.support_mode === "copa_up"
                  ? "Follaje atribuible a la unidad productiva"
                  : "Ventana de muestreo sustituta"}</dd>
              </div>
            </dl>
            <p className="text-xs">
              <strong>Cómo usar esta información:</strong> revisa cada índice junto con
              sus píxeles válidos, el soporte espacial y la observación de campo.
              Una proporción de píxeles válidos no representa hectáreas ni porcentaje
              de plantas sanas. Para decidir intervenciones, se requiere comprobación
              técnica en campo; estos índices no identifican enfermedades, causas ni tratamientos.
            </p>
          </section>
          <p className="muted text-xs">
            Los índices dependen de bandas, calibración y píxeles válidos; sus cifras
            no se deben comparar directamente entre vuelos sin verificar compatibilidad.
          </p>
          <section className="space-y-3" aria-label="Resumen de índices derivados">
            <h3 className="text-sm font-semibold">Resumen de índices · mediana de píxeles válidos</h3>
            <div className="dbi-index-grid">
              {payload.summaries.filter(item => item.variable_kind === "index").map(item => (
                <article className="dbi-index-card" key={item.variable_ref}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">{INDEX_LABELS[item.variable_ref] ?? item.variable_ref}</span>
                    <span className="eyebrow">Derivado</span>
                  </div>
                  <div className="mt-2 text-lg font-semibold tabular-nums">{number(item.median)}</div>
                  <p className="muted mt-1 text-xs">{coverageLabel(item)}</p>
                  <p className="muted mt-2 text-xs">
                    {INDEX_EXPLANATIONS[item.variable_ref] ?? "Índice derivado sin descripción divulgativa validada."}
                  </p>
                </article>
              ))}
              {payload.summaries.every(item => item.variable_kind !== "index") && (
                <p className="muted text-xs">Sin índices derivados autorizados en esta extracción.</p>
              )}
            </div>
          </section>
          <details className="dbi-producer-details">
            <summary className="cursor-pointer text-sm font-semibold">
              Ver estadísticas completas, bandas y procedencia científica
            </summary>
            <div className="mt-4 space-y-5">
              <p className="muted text-xs">
                Mediana = valor central de los píxeles válidos. P10–P90 = intervalo
                entre percentiles 10 y 90, no un umbral de enfermedad.
                Se muestran las versiones de fórmula y fuentes cuando están registradas.
              </p>
              <Statistics heading="Índices derivados · detalle y procedencia" items={payload.summaries.filter(item => item.variable_kind === "index")} />
              <Statistics heading="Bandas fuente resumidas" items={payload.summaries.filter(item => item.variable_kind === "band")} />
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
