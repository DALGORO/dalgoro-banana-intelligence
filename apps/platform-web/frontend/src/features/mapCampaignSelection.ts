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
