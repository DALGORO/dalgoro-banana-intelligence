import { useEffect, useRef, useState } from "react";
import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";
import {
  inspectionVersionMatchesScope,
  isObservationUUID,
  observedNumberLabel,
  type INSPECTReadVersion,
} from "@/features/inspectionEvidenceRead";

function localDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible" : date.toLocaleString("es-EC");
}

function readError(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 401) return "La sesión expiró. Inicia sesión nuevamente.";
  if (status === 403 || status === 404) {
    return "No existe una observación consultable con ese ID para este lote y usuario.";
  }
  if (status === 409) return "La observación no superó la verificación de integridad.";
  if (status === 503) return "INSPECT no está disponible en este momento.";
  return "No se pudo consultar INSPECT. Inténtalo nuevamente.";
}

/**
 * READ bajo petición explícita del usuario y ID exacto.
 * No lista observaciones, no usa caché local, ni abre enlaces a fotos privadas.
 */
export function InspectionObservationLookup({ locator }: {
  locator: PlotMapTimelineLocator;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ scope: string; value: INSPECTReadVersion } | null>(null);
  const requestSequence = useRef(0);
  const scopeKey = JSON.stringify([
    locator.tenantRef, locator.organizationRef, locator.farmId, locator.plotId,
  ]);

  useEffect(() => {
    requestSequence.current += 1;
    setResult(null);
    setError(null);
    setInput("");
    setLoading(false);
    return () => { requestSequence.current += 1; };
  }, [scopeKey]);

  const verified = result?.scope === scopeKey ? result.value : null;

  async function consultObservation() {
    const observationId = input.trim();
    if (!isObservationUUID(observationId) || loading) return;
    const sequence = ++requestSequence.current;
    setResult(null);
    setError(null);
    setLoading(true);
    const url = [
      "/api/v1/dbi/organizations", encodeURIComponent(locator.organizationRef),
      "farms", encodeURIComponent(locator.farmId),
      "plots", encodeURIComponent(locator.plotId),
      "field-observations", encodeURIComponent(observationId),
    ].join("/");
    try {
      const { data } = await api.get<INSPECTReadVersion>(url, {
        headers: { "X-DBI-Tenant": locator.tenantRef },
      });
      if (sequence !== requestSequence.current) return;
      if (!inspectionVersionMatchesScope(data, locator, observationId)) {
        setError("La respuesta INSPECT no coincide con el ID y el alcance autorizados.");
        return;
      }
      setResult({ scope: scopeKey, value: data });
    } catch (cause) {
      if (sequence === requestSequence.current) setError(readError(cause));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }

  return (
    <section className="dbi-inspect-lookup space-y-3" aria-label="Consultar observación INSPECT verificada">
      <div>
        <h4 className="text-sm font-semibold">Consultar observación de campo por ID</h4>
        <p className="muted mt-1 text-xs">
          Introduce el identificador de una observación INSPECT facilitado por el equipo técnico.
          El acceso es de solo lectura y se verifica para este lote.
          Todavía no existe un catálogo general de observaciones consultable desde esta ficha.
        </p>
      </div>
      <form className="space-y-2" onSubmit={event => {
        event.preventDefault();
        void consultObservation();
      }}>
        <label className="text-xs font-medium" htmlFor="dbi-inspect-observation-id">
          ID de la observación
        </label>
        <input
          id="dbi-inspect-observation-id"
          type="text"
          className="w-full"
          autoComplete="off"
          spellCheck={false}
          value={input}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          onChange={event => {
            requestSequence.current += 1;
            setInput(event.target.value);
            setError(null);
            setResult(null);
            setLoading(false);
          }}
        />
        <button type="submit" className="btn-secondary"
          disabled={!isObservationUUID(input) || loading}>
          {loading ? "Consultando…" : "Consultar observación"}
        </button>
      </form>
      {loading && <p role="status" className="muted text-sm">Verificando registro INSPECT autorizado…</p>}
      {error && <p role="alert" className="status-banner status-banner-danger">{error}</p>}
      {verified && (
        <div className="space-y-3">
          <p role="status" className="text-sm font-semibold">
            Observación INSPECT recuperada · versión {verified.version}
          </p>
          <dl className="dbi-tracking-facts">
            <div><dt>Observación de campo</dt><dd>{localDate(verified.payload.observed_at)}</dd></div>
            <div><dt>Registro de versión</dt><dd>{localDate(verified.created_at)}</dd></div>
            <div><dt>Unidad productiva (UP)</dt><dd className="break-all">
              {verified.payload.up_id ?? "Sin ID de UP registrado"}
            </dd></div>
            <div><dt>Punto de muestreo</dt><dd className="break-all">
              {verified.payload.sampling_point_id ?? "Sin punto registrado"}
            </dd></div>
            <div><dt>Ubicación GPS</dt><dd>
              {verified.payload.gps_fix
                ? `GPS registrado · precisión declarada ${verified.payload.gps_fix.accuracy_m} m`
                : "Sin GPS registrado"}
            </dd></div>
          </dl>
          <div className="dbi-tracking-facts" aria-label="Mediciones de campo registradas">
            <div><div className="muted text-xs">Escala Fouré observada</div>
              <div className="mt-1 text-lg font-semibold">{observedNumberLabel(verified.payload.core.foure)}</div>
            </div>
            <div><div className="muted text-xs">YLS observado</div>
              <div className="mt-1 text-lg font-semibold">{observedNumberLabel(verified.payload.core.yls)}</div>
            </div>
            <div><div className="muted text-xs">Hojas funcionales observadas</div>
              <div className="mt-1 text-lg font-semibold">{observedNumberLabel(verified.payload.core.functional_leaves)}</div>
            </div>
          </div>
          <p className="muted text-xs">
            Datos observados, no diagnósticos automáticos. Esta observación se
            recupera por su ID y su alcance, no se atribuye a la Campaign del mapa
            por cercanía temporal o espacial. El ID de UP, cuando existe, es una
            referencia registrada y debe interpretarse con su propia procedencia.
          </p>
        </div>
      )}
    </section>
  );
}
