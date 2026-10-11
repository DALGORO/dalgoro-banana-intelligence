import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";

/** Solo estadísticas derivadas ya autorizadas/validadas por la API. */
export type MultispectralSummary = {
  variable_kind: "band" | "index";
  variable_ref: string;
  evidence_kind: "derived";
  selected_count: number;
  valid_count: number;
  valid_fraction: number;
  mean: number | null;
  median: number | null;
  p10: number | null;
  p90: number | null;
  source_ref: string | null;
  source_sha256: string | null;
  formula_version: string | null;
  formula: string | null;
};

export type MultispectralExtraction = {
  extraction_id: string;
  created_at: string;
  observed_at: string;
  payload: {
    schema_version: "dbi-multispectral-extraction.v1";
    tenant_ref: string;
    organization_ref: string;
    farm_id: string;
    plot_id: string;
    observation_version_id: string;
    source_raster_product_id: string;
    sampling_point_id: string | null;
    up_id: string | null;
    support_mode: "copa_up" | "window";
    support_profile_version: string;
    support_limitation: string | null;
    stack_fingerprint: string;
    selected_count: number;
    evidence_kind: "derived";
    summaries: MultispectralSummary[];
  };
};

export function multispectralScopeKey(locator: PlotMapTimelineLocator): string {
  return JSON.stringify([
    locator.tenantRef, locator.organizationRef, locator.farmId, locator.plotId,
  ]);
}

export async function listMultispectralExtractions(
  locator: PlotMapTimelineLocator,
): Promise<MultispectralExtraction[]> {
  const path = [
    "/api/v1/dbi/organizations", encodeURIComponent(locator.organizationRef),
    "farms", encodeURIComponent(locator.farmId),
    "plots", encodeURIComponent(locator.plotId),
    "multispectral-extractions",
  ].join("/");
  const { data } = await api.get<MultispectralExtraction[]>(path, {
    headers: { "X-DBI-Tenant": locator.tenantRef },
  });
  return data;
}
