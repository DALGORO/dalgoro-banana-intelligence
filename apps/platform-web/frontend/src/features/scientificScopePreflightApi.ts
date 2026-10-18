import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";
import type { ScientificReceptionDraft } from "@/features/scientificReceptionDraft";

export type ScientificScopePreflightResponse = {
  schema_version: "dbi-h14-scientific-scope-preflight.v1";
  disposition: "campaign_scope_verified_only_no_upload";
  campaign_id: string;
  campaign_status: string;
  campaign_link_verified: true;
  file_content_verified: false;
  hashes_verified: false;
  scientific_validated: false;
  server_received: false;
  institutional_approved: false;
  published: false;
};

/** Solo confirma MANAGE y Campaign MULTI scoped. No transmite archivos binarios. */
export async function verifyScientificCampaignScope(
  locator: PlotMapTimelineLocator,
  campaignId: string,
  draft: ScientificReceptionDraft,
): Promise<ScientificScopePreflightResponse> {
  if (!draft.structural_ready || draft.scope.campaign_id !== campaignId) {
    throw new Error("El borrador científico no corresponde a la campaña seleccionada.");
  }
  const address = [
    "/api/v1/dbi/organizations", encodeURIComponent(locator.organizationRef),
    "farms", encodeURIComponent(locator.farmId),
    "plots", encodeURIComponent(locator.plotId),
    "campaigns", encodeURIComponent(campaignId),
    "scientific-intake", "scope-preflight",
  ].join("/");
  const { data } = await api.post<ScientificScopePreflightResponse>(address, draft, {
    headers: { "X-DBI-Tenant": locator.tenantRef },
  });
  if (
    data.schema_version !== "dbi-h14-scientific-scope-preflight.v1"
    || data.disposition !== "campaign_scope_verified_only_no_upload"
    || data.campaign_id.toLowerCase() !== campaignId.toLowerCase()
    || data.campaign_link_verified !== true
    || data.file_content_verified !== false || data.hashes_verified !== false
    || data.scientific_validated !== false || data.server_received !== false
    || data.institutional_approved !== false || data.published !== false
  ) {
    throw new Error("La respuesta de prevalidación de Campaign es inconsistente.");
  }
  return data;
}
