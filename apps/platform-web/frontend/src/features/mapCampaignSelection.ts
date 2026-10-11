/** Selección de capas del mapa: fecha y, cuando se conoce, Campaign exacta. */
export function belongsToSelectedMapCampaign(
  capturedAt: string,
  campaignId: string,
  selectedDate: string,
  exactCampaignId: string | null,
): boolean {
  const first = Date.parse(capturedAt);
  const second = Date.parse(selectedDate);
  const dateMatches = !selectedDate || (
    Number.isFinite(first) && Number.isFinite(second)
      ? first === second : capturedAt === selectedDate
  );
  return dateMatches && (!exactCampaignId || campaignId === exactCampaignId);
}

/**
 * Identidad completa de la vista: al cambiar tenant o ruta agrícola,
 * React desmonta mapa, panel MULTI, cachés GIS y selecciones previas.
 * Se usa el tenant normalizado de la URL; no genera ni concede permisos.
 */
export function mapTimelineViewKey(scope: {
  tenantRef: string;
  organizationRef?: string;
  farmId?: string;
  plotId?: string;
  fincaId?: string;
}): string {
  return JSON.stringify([
    scope.tenantRef,
    scope.organizationRef ?? null,
    scope.farmId ?? null,
    scope.plotId ?? null,
    scope.fincaId ?? null,
  ]);
}
