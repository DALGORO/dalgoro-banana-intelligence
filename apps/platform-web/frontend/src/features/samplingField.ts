import { api } from "@/app/api";

export const SAMPLING_REJECTION_REASONS = [
  "road",
  "infrastructure",
  "canal_or_drain",
  "non_banana",
  "missing_plant",
  "inaccessible",
  "unsafe",
  "other",
] as const;

export type SamplingRejectionReason =
  (typeof SAMPLING_REJECTION_REASONS)[number];

export type SamplingPointRole = "primary" | "reserve";
export type SamplingPointStatus =
  | "planned"
  | "validated"
  | "rejected"
  | "substituted";
export type SamplingPlanStatus = "planned" | "in_field" | "completed" | "retired";

export type GeoJSONMultiPolygon = {
  type: "MultiPolygon";
  coordinates: number[][][][];
};

export type SamplingPoint = {
  point_id: string;
  role: SamplingPointRole;
  sequence: number;
  route_order: number | null;
  reserve_for_sequence: number | null;
  selection_reason: "balanced" | "nearby_reserve";
  planned_longitude: number;
  planned_latitude: number;
  observed_longitude: number | null;
  observed_latitude: number | null;
  status: SamplingPointStatus;
  rejection_reason: SamplingRejectionReason | null;
  observed_at: string | null;
};

export type SamplingPlan = {
  plan_id: string;
  schema_version: string;
  profile_version: string;
  profile: Record<string, unknown>;
  budget: Record<string, unknown>;
  boundary_sha256: string;
  exclusions_sha256: string;
  boundary: GeoJSONMultiPolygon;
  exclusions: GeoJSONMultiPolygon | null;
  status: SamplingPlanStatus;
  created_at: string;
  points: SamplingPoint[];
};

export type SamplingPlanLocator = {
  tenantRef?: string;
  organizationRef: string;
  farmId: string;
  plotId: string;
  planId: string;
};

export type SamplingOutboxState =
  | "pending"
  | "syncing"
  | "conflict"
  | "auth_required"
  | "failed";

export type SamplingValidatePayload = {
  longitude: number;
  latitude: number;
  observed_at: string;
};

export type SamplingRejectPayload = {
  rejection_reason: SamplingRejectionReason;
  observed_at: string;
};

export type SamplingSubstitutePayload = SamplingValidatePayload & {
  reserve_point_id: string;
  rejection_reason: SamplingRejectionReason;
};

type SamplingOutboxBase = {
  actionId: string;
  planKey: string;
  tenantRef: string;
  locator: SamplingPlanLocator;
  pointId: string;
  state: SamplingOutboxState;
  createdAt: string;
  updatedAt: string;
  attemptCount: number;
  lastError: string | null;
};

export type SamplingOutboxAction =
  | (SamplingOutboxBase & {
      kind: "validate";
      payload: SamplingValidatePayload;
    })
  | (SamplingOutboxBase & {
      kind: "reject";
      payload: SamplingRejectPayload;
    })
  | (SamplingOutboxBase & {
      kind: "substitute";
      payload: SamplingSubstitutePayload;
    });

export type SamplingActionDraft =
  | {
      kind: "validate";
      pointId: string;
      payload: SamplingValidatePayload;
    }
  | {
      kind: "reject";
      pointId: string;
      payload: SamplingRejectPayload;
    }
  | {
      kind: "substitute";
      pointId: string;
      payload: SamplingSubstitutePayload;
    };

const TENANT_QUERY_PARAM = "tenant";
const MISSING_TENANT_CACHE_KEY = "__missing_tenant__";

function encoded(value: string) {
  return encodeURIComponent(value);
}

/**
 * El frontend transporta el tenant seleccionado; nunca lo usa como autoridad.
 * La membresía y los scopes continúan siendo resueltos y validados por DBI.
 */
export function samplingTenantRef(locator?: SamplingPlanLocator): string | null {
  const explicit = locator?.tenantRef?.trim();
  if (explicit) return explicit;

  if (typeof window === "undefined") return null;
  const fromQuery = new URLSearchParams(window.location.search)
    .get(TENANT_QUERY_PARAM)
    ?.trim();
  return fromQuery || null;
}

function requireSamplingTenantRef(locator: SamplingPlanLocator): string {
  const tenantRef = samplingTenantRef(locator);
  if (!tenantRef) {
    throw new Error(
      "La ruta Sampling requiere un tenant DBI explícito mediante ?tenant=<tenant_ref>.",
    );
  }
  return tenantRef;
}

function samplingHeaders(tenantRef: string) {
  return { "X-DBI-Tenant": tenantRef };
}

export function samplingPlanKey(locator: SamplingPlanLocator) {
  const tenantRef = samplingTenantRef(locator) ?? MISSING_TENANT_CACHE_KEY;
  return [
    tenantRef,
    locator.organizationRef,
    locator.farmId,
    locator.plotId,
    locator.planId,
  ]
    .map(encoded)
    .join("|");
}

function samplingPlanUrl(locator: SamplingPlanLocator) {
  return [
    "/api/v1/dbi/organizations",
    encoded(locator.organizationRef),
    "farms",
    encoded(locator.farmId),
    "plots",
    encoded(locator.plotId),
    "sampling-plans",
    encoded(locator.planId),
  ].join("/");
}

export async function getSamplingPlan(
  locator: SamplingPlanLocator,
): Promise<SamplingPlan> {
  const tenantRef = requireSamplingTenantRef(locator);
  const { data } = await api.get<SamplingPlan>(samplingPlanUrl(locator), {
    headers: samplingHeaders(tenantRef),
  });
  return data;
}

export function createSamplingOutboxAction(
  locator: SamplingPlanLocator,
  draft: SamplingActionDraft,
): SamplingOutboxAction {
  const now = new Date().toISOString();
  const tenantRef = requireSamplingTenantRef(locator);
  const common: SamplingOutboxBase = {
    actionId: crypto.randomUUID(),
    planKey: samplingPlanKey({ ...locator, tenantRef }),
    tenantRef,
    locator: { ...locator, tenantRef },
    pointId: draft.pointId,
    state: "pending",
    createdAt: now,
    updatedAt: now,
    attemptCount: 0,
    lastError: null,
  };

  if (draft.kind === "validate") {
    return { ...common, kind: draft.kind, payload: draft.payload };
  }
  if (draft.kind === "reject") {
    return { ...common, kind: draft.kind, payload: draft.payload };
  }
  return { ...common, kind: draft.kind, payload: draft.payload };
}

export async function sendSamplingOutboxAction(
  action: SamplingOutboxAction,
): Promise<void> {
  const tenantRef = action.tenantRef?.trim();
  if (!tenantRef) {
    throw new Error("La acción offline no contiene un tenant DBI explícito.");
  }

  const base = samplingPlanUrl(action.locator);
  const pointId = encoded(action.pointId);
  const config = { headers: samplingHeaders(tenantRef) };

  if (action.kind === "validate") {
    await api.post(`${base}/points/${pointId}/validate`, action.payload, config);
    return;
  }
  if (action.kind === "reject") {
    await api.post(`${base}/points/${pointId}/reject`, action.payload, config);
    return;
  }
  await api.post(`${base}/points/${pointId}/substitute`, action.payload, config);
}

export type DevicePosition = {
  longitude: number;
  latitude: number;
  accuracyM: number;
  capturedAt: string;
};

export function distanceMeters(
  longitudeA: number,
  latitudeA: number,
  longitudeB: number,
  latitudeB: number,
) {
  const earthRadiusM = 6_371_008.8;
  const toRadians = (value: number) => (value * Math.PI) / 180;
  const latitudeARad = toRadians(latitudeA);
  const latitudeBRad = toRadians(latitudeB);
  const deltaLatitude = toRadians(latitudeB - latitudeA);
  const deltaLongitude = toRadians(longitudeB - longitudeA);
  const haversine =
    Math.sin(deltaLatitude / 2) ** 2 +
    Math.cos(latitudeARad) *
      Math.cos(latitudeBRad) *
      Math.sin(deltaLongitude / 2) ** 2;
  return 2 * earthRadiusM * Math.asin(Math.min(1, Math.sqrt(haversine)));
}
