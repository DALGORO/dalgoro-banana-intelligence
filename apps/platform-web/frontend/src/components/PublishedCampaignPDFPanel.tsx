import { useEffect, useState } from "react";
import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";

type State = { key: string; url: string | null; error: string | null; loading: boolean };
const inactive: State = { key: "", url: null, error: null, loading: false };

/**
 * Vista previa de ficha PDF sólo desde el servidor (Campaign publicada).
 * Nunca crea ni publica resultados. El acceso READ + status PUBLISHED se
 * comprueba en FastAPI; un 404 no se interpreta como cero hallazgos.
 */
export function PublishedCampaignPDFPanel({
  locator, campaignId,
}: { locator: PlotMapTimelineLocator; campaignId: string | null }) {
  const [state, setState] = useState<State>(inactive);
  const key = JSON.stringify([
    locator.tenantRef, locator.organizationRef,
    locator.farmId, locator.plotId, campaignId,
  ]);
  const current = state.key === key ? state : inactive;

  useEffect(() => () => {
    if (state.url) URL.revokeObjectURL(state.url);
  }, [state.url]);

  const openPDF = async () => {
    if (!campaignId || current.loading) return;
    setState({ key, url: null, error: null, loading: true });
    const endpoint = [
      "/api/v1/dbi/organizations", encodeURIComponent(locator.organizationRef),
      "farms", encodeURIComponent(locator.farmId),
      "plots", encodeURIComponent(locator.plotId),
      "campaigns", encodeURIComponent(campaignId), "published-evidence.pdf",
    ].join("/");
    try {
      const response = await api.get<Blob>(endpoint, {
        responseType: "blob", headers: { "X-DBI-Tenant": locator.tenantRef },
      });
      if (response.data.type !== "application/pdf") throw new Error("invalid_pdf");
      const url = URL.createObjectURL(response.data);
      setState({ key, url, error: null, loading: false });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      setState({
        key, url: null, loading: false,
        error: status === 404
          ? "Todavía no hay una ficha PDF aprobada y publicada para este levantamiento."
          : "No fue posible consultar el PDF. Comprueba la conexión o vuelve a intentarlo.",
      });
    }
  };

  return (
    <section className="dbi-published-pdf space-y-2" aria-label="Informe PDF publicado">
      <h4 className="text-sm font-semibold">Informe PDF del levantamiento</h4>
      <p className="muted text-xs">
        La ficha se genera exclusivamente con datos persistidos de una campaña aprobada
        y publicada. No equivale al informe técnico completo de densidad.
      </p>
      {!campaignId ? (
        <p className="muted text-xs">Selecciona primero un levantamiento específico.</p>
      ) : (
        <>
          <button className="btn-secondary" type="button" onClick={() => void openPDF()}
            disabled={current.loading}>
            {current.loading ? "Consultando informe…" : "Consultar PDF publicado"}
          </button>
          {current.error && <p role="status" className="text-sm text-amber-700">{current.error}</p>}
          {current.url && (
            <div className="space-y-2">
              <iframe src={current.url} title="Vista previa del PDF del levantamiento publicado"
                className="dbi-published-pdf-frame" />
              <a className="btn-secondary inline-flex" href={current.url}
                download="dalgoro_evidencias_publicadas.pdf">Descargar PDF</a>
            </div>
          )}
        </>
      )}
    </section>
  );
}
