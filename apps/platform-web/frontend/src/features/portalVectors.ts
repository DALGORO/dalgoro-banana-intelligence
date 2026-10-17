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

export type GISImportReceipt = {
  id: string;
  campaign_id: string;
  name: string;
  original_filename: string;
  source_format: "gpkg" | "shp_zip";
  layer_kind: VectorLayerKind;
  size_bytes: number;
  status: "received" | "processing" | "needs_selection" | "prepared" | "published" | "failed";
  available_layers: string[] | null;
  selected_layer: string | null;
  published_layer_id: string | null;
  created_at: string;
};

export type VectorCampaign = {
  id: string;
  name: string;
  captured_at: string;
  analysis_type: "density" | "multispectral";
  status: string;
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

export async function listVectorCampaigns(locator: PlotMapTimelineLocator) {
  const campaignsUrl = url(locator).replace(/\/vector-layers$/, "/vector-campaigns");
  const { data } = await api.get<VectorCampaign[]>(campaignsUrl, {
    headers: headers(locator.tenantRef),
  });
  return data;
}

/** Gestores MANAGE: permite revisar campañas no publicadas sin mostrarlas al cliente READ. */
export async function listManagementCampaigns(locator: PlotMapTimelineLocator) {
  const managementUrl = url(locator).replace(/\/vector-layers$/, "/management-campaigns");
  const { data } = await api.get<VectorCampaign[]>(managementUrl, {
    headers: headers(locator.tenantRef),
  });
  return data;
}

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

function importsUrl(locator: PlotMapTimelineLocator) {
  return url(locator).replace(/\/vector-layers$/, "/gis-imports");
}

export async function listGISImports(locator: PlotMapTimelineLocator) {
  const { data } = await api.get<GISImportReceipt[]>(importsUrl(locator), {
    headers: headers(locator.tenantRef),
  });
  return data;
}

export async function stageGISOriginal(
  locator: PlotMapTimelineLocator,
  file: File, campaignId: string,
  kind: VectorLayerKind, name: string,
) {
  const query = new URLSearchParams({
    filename: file.name, campaign_id: campaignId, layer_kind: kind, name,
  });
  const { data } = await api.post<GISImportReceipt>(
    `${importsUrl(locator)}?${query.toString()}`, file,
    {
      headers: { ...headers(locator.tenantRef), "Content-Type": "application/octet-stream" },
    },
  );
  return data;
}

export async function selectGISImportLayer(
  locator: PlotMapTimelineLocator, importId: string, layer: string,
) {
  const { data } = await api.post<GISImportReceipt>(
    `${importsUrl(locator)}/${encodeURIComponent(importId)}/select-layer`,
    { layer },
    { headers: headers(locator.tenantRef) },
  );
  return data;
}

export type GISImportPreview = {
  receipt: GISImportReceipt;
  feature_count: number;
  geojson: GeoJSONFeatureCollection;
};

export async function getGISImportPreview(locator: PlotMapTimelineLocator, importId: string) {
  const { data } = await api.get<GISImportPreview>(
    `${importsUrl(locator)}/${encodeURIComponent(importId)}/preview`,
    { headers: headers(locator.tenantRef) },
  );
  return data;
}

export async function publishReviewedGISImport(locator: PlotMapTimelineLocator, importId: string) {
  const { data } = await api.post<VectorLayerInfo>(
    `${importsUrl(locator)}/${encodeURIComponent(importId)}/publish`,
    null, { headers: headers(locator.tenantRef) },
  );
  return data;
}

/** Encuadre de capas vectoriales reales cuando el lote no posee ortofoto/viewport. */
export function vectorExtent(
  vectors: VectorLayerDetail[],
): [number, number, number, number] | null {
  let west = 180, south = 90, east = -180, north = -90;
  let found = false;

  function visit(node: unknown): void {
    if (!Array.isArray(node) || node.length === 0) return;
    if (
      node.length >= 2
      && typeof node[0] === "number"
      && typeof node[1] === "number"
    ) {
      const [lon, lat] = node as number[];
      if (!Number.isFinite(lon) || !Number.isFinite(lat) ||
          lon < -180 || lon > 180 || lat < -90 || lat > 90) return;
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
      found = true;
    } else {
      for (const child of node) visit(child);
    }
  }
  for (const vector of vectors) {
    for (const feature of vector.geojson.features) {
      visit(feature.geometry.coordinates);
    }
  }
  if (!found) return null;
  const longitudePad = Math.max((east - west) * 0.08, 0.0001);
  const latitudePad = Math.max((north - south) * 0.08, 0.0001);
  return [
    Math.max(-180, west - longitudePad),
    Math.max(-90, south - latitudePad),
    Math.min(180, east + longitudePad),
    Math.min(90, north + latitudePad),
  ];
}
