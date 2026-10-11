import type { MapTimelineEntry, PlotMapTimelineLocator } from "@/features/mapTimeline";
import { InspectionObservationLookup } from "@/components/InspectionObservationLookup";
import type { VectorLayerInfo } from "@/features/portalVectors";

type Props = {
  farmName: string;
  plotName: string;
  selectedMapDate: string;
  selectedCampaignId: string | null;
  visibleMapEntries: readonly MapTimelineEntry[];
  associatedGISLayers: readonly VectorLayerInfo[];
  loading: boolean;
  timelineError: string | null;
  hasScopedPlot: boolean;
  locator: PlotMapTimelineLocator | null;
  onOpenEvidence: () => void;
};

function capturedTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible"
    : date.toLocaleString("es-EC");
}

/**
 * Ficha exclusivamente de lectura, construida con el MISMO estado ya autorizado
 * por la cronología de mapa. Sin consultas adicionales, cambios de rol o inferencias.
 */
export function FarmTrackingPanel({
  farmName, plotName, selectedMapDate, selectedCampaignId,
  visibleMapEntries, associatedGISLayers, loading, timelineError,
  hasScopedPlot, locator, onOpenEvidence,
}: Props) {
  const visibleObservations = visibleMapEntries.filter(
    entry => entry.layer_type === "inspections",
  );
  const inspectionGIS = associatedGISLayers.filter(
    layer => layer.layer_kind === "observations",
  );

  return (
    <section className="dbi-tracking-panel space-y-4" aria-label="Ficha de seguimiento del lote">
      <div>
        <div className="eyebrow">Consulta de información existente</div>
        <h3 className="mt-1 text-lg font-semibold">Seguimiento del lote</h3>
        <p className="muted mt-1 text-sm">
          Consulta la procedencia y los registros disponibles para la selección del mapa.
          Esta ficha no diagnostica enfermedades ni determina intervenciones.
        </p>
      </div>

      <dl className="dbi-tracking-facts">
        <div><dt>Finca</dt><dd>{farmName}</dd></div>
        <div><dt>Lote</dt><dd>{hasScopedPlot ? plotName : "Lote no identificado en este enlace"}</dd></div>
        <div>
          <dt>Fecha cartográfica seleccionada</dt>
          <dd>{selectedMapDate ? capturedTime(selectedMapDate) : "Todas las fechas"}</dd>
        </div>
        <div>
          <dt>Campaign MULTI específica</dt>
          <dd className="break-all">{selectedCampaignId ?? "Sin Campaign exacta seleccionada"}</dd>
        </div>
      </dl>

      {loading && <p role="status" className="muted text-sm">Cargando registros del mapa…</p>}
      {timelineError && <p role="alert" className="status-banner status-banner-danger">{timelineError}</p>}
      {!loading && !timelineError && (
        <>
          <div className="dbi-tracking-facts" aria-label="Evidencias de la selección">
            <div>
              <div className="muted text-xs">Registros cartográficos activados</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">{visibleMapEntries.length}</div>
            </div>
            <div>
              <div className="muted text-xs">Capas GIS asociadas a la selección</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">{associatedGISLayers.length}</div>
            </div>
          </div>

          <section aria-label="Registros visibles de la campaña" className="space-y-2">
            <h4 className="text-sm font-semibold">Evidencias visibles en el mapa</h4>
            {visibleMapEntries.length > 0 ? (
              <ul className="dbi-tracking-list">
                {visibleMapEntries.slice(0, 6).map(entry => (
                  <li key={entry.entry_id}>
                    <span className="block text-sm font-medium">{entry.title}</span>
                    <span className="muted block text-xs">
                      {capturedTime(entry.captured_at)} · {entry.layer_type.toUpperCase()}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted text-sm">
                No hay registros cartográficos activados para esta selección.
                Revisa la fecha y las capas del mapa; esto no significa que la finca no tenga datos.
              </p>
            )}
            {visibleMapEntries.length > 6 && (
              <p className="muted text-xs">
                Se muestran 6 de {visibleMapEntries.length} registros de esta selección.
              </p>
            )}
          </section>

          <section className="space-y-2" aria-label="Consulta de observaciones disponibles">
            <h4 className="text-sm font-semibold">Observaciones y verificaciones</h4>
            <p className="muted text-sm">
              {visibleObservations.length} registros de tipo inspección activados en la cronología.
              {" "}{inspectionGIS.length} capas GIS de observaciones asociadas a la selección.
            </p>
            <p className="muted text-xs">
              Estas cifras describen registros y capas, no inspecciones individuales verificadas
              ni unidades productivas enfermas. No se deduce su relación por proximidad o fecha.
            </p>
          </section>
          {locator && (
            <InspectionObservationLookup
              key={JSON.stringify([locator.tenantRef, locator.organizationRef, locator.farmId, locator.plotId])}
              locator={locator}
            />
          )}
        </>
      )}

      <section className="dbi-tracking-next space-y-2" aria-label="Próximo paso de consulta">
        <h4 className="text-sm font-semibold">¿Qué conviene revisar?</h4>
        <p className="text-sm">
          {!hasScopedPlot
            ? "Para consultar evidencias MULTI por lote, ingresa mediante una ruta autorizada de finca y lote."
            : !selectedMapDate
              ? "Selecciona una fecha real en el mapa y comprueba qué productos están disponibles."
              : !selectedCampaignId
                ? "Si necesitas índices MULTI atribuidos a un vuelo, selecciona una Campaign verificada en Evidencia MULTI. Una fecha sola puede no ser suficiente."
                : "Puedes consultar las bandas y los índices derivados de la Campaign seleccionada, con su soporte espacial y píxeles válidos."}
        </p>
        {hasScopedPlot && (
          <button className="btn-secondary" type="button" onClick={onOpenEvidence}>
            Consultar evidencia multiespectral
          </button>
        )}
      </section>
      <p className="muted text-xs">
        Ficha de consulta, no informe agronómico. La ausencia de registros visibles
        no confirma ausencia de inspecciones, vuelos o problemas en el cultivo.
      </p>
    </section>
  );
}
