import type { PlotMapTimelineLocator } from "./mapTimeline";
import type { MultispectralExtraction } from "./multispectralEvidence";

/** Historial solo de Campaign con cadena científica verificada, no fecha inferida. */
export type VerifiedMultispectralCampaign = {
  campaignId: string;
  capturedAt: string;
  extractionCount: number;
  latestExtractionId: string;
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ZONED_TIMESTAMP = /T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i;

function zonedTime(raw: unknown): number | null {
  if (typeof raw !== "string" || !ZONED_TIMESTAMP.test(raw)) return null;
  const millis = Date.parse(raw);
  return Number.isFinite(millis) ? millis : null;
}

/**
 * La lista READ está limitada a 20 por backend. Este índice no usa nombres,
 * fechas INSPECT ni proximidad temporal para asignar campañas.
 * Una misma Campaign con capturas contradictorias queda completamente excluida.
 */
export function verifiedMultispectralCampaigns(
  items: readonly MultispectralExtraction[],
  scope: PlotMapTimelineLocator,
): VerifiedMultispectralCampaign[] {
  const groups = new Map<string, {
    capturedAt: number;
    extractionCount: number;
    latestExtractionId: string;
    latestRegistered: number;
    seenIds: Set<string>;
  }>();
  const ambiguous = new Set<string>();
  for (const item of items.slice(0, 20)) {
    const payload = item.payload;
    if (!payload
      || payload.tenant_ref !== scope.tenantRef
      || payload.organization_ref !== scope.organizationRef
      || payload.farm_id !== scope.farmId
      || payload.plot_id !== scope.plotId
      || item.campaign_linkage !== "verified_job_chain"
      || typeof item.campaign_id !== "string"
      || !UUID_PATTERN.test(item.campaign_id)
      || typeof item.extraction_id !== "string"
      || !UUID_PATTERN.test(item.extraction_id)) continue;

    const captured = zonedTime(item.captured_at);
    if (captured === null || ambiguous.has(item.campaign_id)) continue;
    const registered = zonedTime(item.created_at) ?? 0;
    const existing = groups.get(item.campaign_id);
    if (existing && existing.capturedAt !== captured) {
      ambiguous.add(item.campaign_id);
      groups.delete(item.campaign_id);
      continue;
    }
    if (existing) {
      if (existing.seenIds.has(item.extraction_id)) continue;
      existing.seenIds.add(item.extraction_id);
      existing.extractionCount += 1;
      if (registered > existing.latestRegistered) {
        existing.latestRegistered = registered;
        existing.latestExtractionId = item.extraction_id;
      }
    } else {
      groups.set(item.campaign_id, {
        capturedAt: captured,
        extractionCount: 1,
        latestExtractionId: item.extraction_id,
        latestRegistered: registered,
        seenIds: new Set([item.extraction_id]),
      });
    }
  }
  return [...groups.entries()]
    .map(([campaignId, row]) => ({
      campaignId,
      capturedAt: new Date(row.capturedAt).toISOString(),
      extractionCount: row.extractionCount,
      latestExtractionId: row.latestExtractionId,
    }))
    .sort((a, b) => {
      const difference = Date.parse(b.capturedAt) - Date.parse(a.capturedAt);
      return difference || a.campaignId.localeCompare(b.campaignId);
    });
}
