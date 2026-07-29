import { api } from "@/app/api";

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

export type FarmMapTimelineResponse = {
  schema_version: "farm-map-timeline.v1";
  farm_id: string;
  status: "awaiting_data";
  available_layers: MapLayerCatalogEntry[];
  timeline: MapTimelineEntry[];
  comparison: {
    minimum_dates: 2;
    available_dates: string[];
    enabled: boolean;
  };
};

export async function getFarmMapTimeline(
  farmId: string,
): Promise<FarmMapTimelineResponse> {
  const { data } = await api.get<FarmMapTimelineResponse>(
    `/api/v1/dbi/farms/${encodeURIComponent(farmId)}/map/timeline`,
  );
  return data;
}
