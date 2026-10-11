import { api } from "@/app/api";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";

export type VectorLayerKind =
  | "plants" | "density_hexagons" | "planting_candidates"
  | "boundaries" | "observations" | "other";

export type GeoJSONFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: string; coordinates: unknown };
    properties: Record<string, string | number | boolean | null>;
  }>;
};

export type VectorLayerInfo = {
  id: string;
  campaign_id: string;
  name: string;
  layer_kind: VectorLayerKind;
  feature_count: number;
  created_at: string;
};

export type VectorLayerDetail = {
  layer: VectorLayerInfo;
  geojson: GeoJSONFeatureCollection;
};

function url(locator: PlotMapTimelineLocator) {
  return [
    "/api/v1/dbi/organizations",
    encodeURIComponent(locator.organizationRef),
    "farms", encodeURIComponent(locator.farmId),
    "plots", encodeURIComponent(locator.plotId),
    "map", "vector-layers",
  ].join("/");
}
const headers = (tenantRef: string) => ({ "X-DBI-Tenant": tenantRef });

export async function listVectorLayers(locator: PlotMapTimelineLocator) {
  const { data } = await api.get<VectorLayerInfo[]>(url(locator), {
    headers: headers(locator.tenantRef),
  });
  return data;
}

export async function getVectorLayer(locator: PlotMapTimelineLocator, id: string) {
  const { data } = await api.get<VectorLayerDetail>(
    `${url(locator)}/${encodeURIComponent(id)}`,
    { headers: headers(locator.tenantRef) },
  );
  return data;
}

export async function publishGeoJSON(
  locator: PlotMapTimelineLocator,
  file: File,
  campaignId: string,
  kind: VectorLayerKind,
  title: string,
) {
  const query = new URLSearchParams({
    campaign_id: campaignId, layer_kind: kind, name: title,
  });
  const { data } = await api.post<VectorLayerInfo>(
    `${url(locator)}?${query.toString()}`,
    file,
    {
      headers: {
        ...headers(locator.tenantRef),
        "Content-Type": "application/geo+json",
      },
    },
  );
  return data;
}
