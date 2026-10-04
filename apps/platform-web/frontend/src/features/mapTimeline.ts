import { api, apiBaseUrl } from "@/app/api";

export type MapLayerType =
  | "rgb"
  | "ndvi"
  | "ndre"
  | "density"
  | "anomalies"
  | "inspections"
  | "production"
  | "sst";

export type EvidenceClassification =
  | "observed"
  | "inference"
  | "hypothesis"
  | "recommendation";

export type ProfessionalReviewStatus =
  | "not_required"
  | "pending"
  | "approved"
  | "rejected";

export type MapLayerCatalogEntry = {
  layer_type: MapLayerType;
  label: string;
  description: string;
  default_classification: EvidenceClassification;
};

export type MapTimelineEntry = {
  entry_id: string;
  layer_type: MapLayerType;
  captured_at: string;
  title: string;
  classification: EvidenceClassification;
  source_artifact_id: string;
  confidence: {
    level: "low" | "medium" | "high";
    score: number | null;
    method_ref: string;
  } | null;
  professional_review_status: ProfessionalReviewStatus;
};

export type RasterTileTimelineEntry = MapTimelineEntry & {
  campaign_id: string;
  plot_id: string;
  layer_type: "rgb";
  raster_product_id: string;
  tile_url_template: string;
};

export type MapComparisonCapability = {
  minimum_dates: 2;
  available_dates: string[];
  enabled: boolean;
};

export type FarmMapTimelineResponse = {
  schema_version: "farm-map-timeline.v1";
  farm_id: string;
  status: "awaiting_data";
  available_layers: MapLayerCatalogEntry[];
  timeline: MapTimelineEntry[];
  comparison: MapComparisonCapability;
};

export type PlotMapTimelineResponse = {
  schema_version: "plot-map-timeline.v1";
  organization_ref: string;
  farm_id: string;
  plot_id: string;
  status: "awaiting_data" | "ready";
  available_layers: MapLayerCatalogEntry[];
  timeline: RasterTileTimelineEntry[];
  comparison: MapComparisonCapability;
  viewport_bounds: [number, number, number, number] | null;
};

export type PlotMapTimelineLocator = {
  tenantRef: string;
  organizationRef: string;
  farmId: string;
  plotId: string;
};

function encoded(value: string) {
  return encodeURIComponent(value);
}

function dbiHeaders(tenantRef: string) {
  return { "X-DBI-Tenant": tenantRef };
}

export function apiResourceUrl(path: string) {
  if (!path.startsWith("/")) {
    throw new Error("La ruta API debe ser absoluta dentro del origen.");
  }
  return apiBaseUrl ? `${apiBaseUrl}${path}` : path;
}

export async function getFarmMapTimeline(
  farmId: string,
): Promise<FarmMapTimelineResponse> {
  const { data } = await api.get<FarmMapTimelineResponse>(
    `/api/v1/dbi/farms/${encoded(farmId)}/map/timeline`,
  );
  return data;
}

export async function getPlotMapTimeline(
  locator: PlotMapTimelineLocator,
): Promise<PlotMapTimelineResponse> {
  const tenantRef = locator.tenantRef.trim();
  if (!tenantRef) {
    throw new Error("La cronología Raster requiere un tenant DBI explícito.");
  }

  const url = [
    "/api/v1/dbi/organizations",
    encoded(locator.organizationRef),
    "farms",
    encoded(locator.farmId),
    "plots",
    encoded(locator.plotId),
    "map",
    "timeline",
  ].join("/");

  const { data } = await api.get<PlotMapTimelineResponse>(url, {
    headers: dbiHeaders(tenantRef),
  });
  return data;
}

export function mapLibreDbiHeaders(tenantRef: string) {
  const headers: Record<string, string> = {
    "X-DBI-Tenant": tenantRef,
  };
  const token = localStorage.getItem("token");
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}
