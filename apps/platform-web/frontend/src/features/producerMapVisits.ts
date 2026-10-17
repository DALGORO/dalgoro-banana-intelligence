import type { RasterTileTimelineEntry } from "./mapTimeline";
import type { VectorCampaign, VectorLayerInfo } from "./portalVectors";

/** Historial solo de cartografía existente y autorizada; nunca de campañas sin mapa. */
export type ProducerMapVisit = {
  campaignId: string;
  capturedAt: string;
  name: string;
  hasRgb: boolean;
  gisLayerCount: number;
  reviewStatus: "approved" | "pending" | "not_reported";
};

function timestamp(value: string): number | null {
  const date = Date.parse(value);
  return Number.isFinite(date) ? date : null;
}

export function producerMapVisits(
  rasters: readonly RasterTileTimelineEntry[],
  campaigns: readonly VectorCampaign[],
  vectors: readonly VectorLayerInfo[],
): ProducerMapVisit[] {
  const visits = new Map<string, ProducerMapVisit>();
  const ambiguous = new Set<string>();
  for (const entry of rasters) {
    if (entry.layer_type !== "rgb" || !entry.campaign_id || timestamp(entry.captured_at) === null
      || ambiguous.has(entry.campaign_id)) continue;
    const existing = visits.get(entry.campaign_id);
    if (existing && timestamp(existing.capturedAt) !== timestamp(entry.captured_at)) {
      // Una cadena contradictoria no puede convertirse en un vuelo seleccionable.
      visits.delete(entry.campaign_id);
      ambiguous.add(entry.campaign_id);
      continue;
    }
    if (!existing) visits.set(entry.campaign_id, {
      campaignId: entry.campaign_id, capturedAt: entry.captured_at,
      name: entry.title, hasRgb: true, gisLayerCount: 0,
      reviewStatus: entry.professional_review_status === "approved" ? "approved" : "pending",
    });
  }
  const vectorCounts = new Map<string, number>();
  for (const layer of vectors) vectorCounts.set(layer.campaign_id, (vectorCounts.get(layer.campaign_id) ?? 0) + 1);
  for (const campaign of campaigns) {
    const count = vectorCounts.get(campaign.id) ?? 0;
    if (!count || timestamp(campaign.captured_at) === null || ambiguous.has(campaign.id)) continue;
    const existing = visits.get(campaign.id);
    if (existing) {
      if (timestamp(existing.capturedAt) === timestamp(campaign.captured_at)) existing.gisLayerCount = count;
    } else {
      visits.set(campaign.id, {
        campaignId: campaign.id, capturedAt: campaign.captured_at,
        name: campaign.name, hasRgb: false, gisLayerCount: count, reviewStatus: "not_reported",
      });
    }
  }
  return [...visits.values()].sort((a, b) =>
    (timestamp(b.capturedAt) ?? 0) - (timestamp(a.capturedAt) ?? 0)
      || a.campaignId.localeCompare(b.campaignId)
  );
}

export function visitsAtDate(visits: readonly ProducerMapVisit[], date: string): ProducerMapVisit[] {
  const selectedTime = timestamp(date);
  if (selectedTime === null) return [];
  return visits.filter(visit => timestamp(visit.capturedAt) === selectedTime);
}
