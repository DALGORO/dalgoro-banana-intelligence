import { api } from "@/app/api";

export type InspectionFieldState = "observed" | "not_measured" | "not_applicable";

export type InspectionObservedValue<T> = {
  state: InspectionFieldState;
  value: T | null;
  reason: string | null;
};

export type InspectionPhotoEvidence = {
  state: InspectionFieldState;
  asset_id: string | null;
  reason: string | null;
};

export type InspectionGPSFix = {
  longitude: number;
  latitude: number;
  accuracy_m: number;
  captured_at: string;
};

export type InspectionCoreObservation = {
  foure: InspectionObservedValue<number>;
  yls: InspectionObservedValue<number>;
  functional_leaves: InspectionObservedValue<number>;
  mother_condition: InspectionObservedValue<string>;
  successor_condition: InspectionObservedValue<string>;
  bunch_present: InspectionObservedValue<boolean>;
  visible_affection: InspectionObservedValue<string>;
  severity: InspectionObservedValue<string>;
  observer_confidence: InspectionObservedValue<string>;
  general_photo: InspectionPhotoEvidence;
  lesion_photo: InspectionPhotoEvidence;
  note: string | null;
};

export type InspectionFieldObservationBody = {
  observed_at: string;
  gps_fix: InspectionGPSFix | null;
  sampling_point_id: string | null;
  up_id: string | null;
  core: InspectionCoreObservation;
  structural: null;
  diagnostic: null;
};

export type InspectionCreateRequest = {
  observation: InspectionFieldObservationBody;
};

export type InspectionVersion = {
  schema_version: "dbi-field-observation.v1";
  observation_id: string;
  version_id: string;
  version: number;
  supersedes_version_id: string | null;
  correction_reason: string | null;
  created_at: string;
  payload: Record<string, unknown>;
};

export type InspectionLocator = {
  tenantRef?: string;
  organizationRef: string;
  farmId: string;
  plotId: string;
};

export type InspectionOutboxState =
  | "pending"
  | "syncing"
  | "conflict"
  | "auth_required"
  | "failed";

export type InspectionOutboxAction = {
  actionId: string;
  plotKey: string;
  tenantRef: string;
  locator: InspectionLocator;
  observationId: string;
  versionId: string;
  request: InspectionCreateRequest;
  state: InspectionOutboxState;
  createdAt: string;
  updatedAt: string;
  attemptCount: number;
  lastError: string | null;
};

const TENANT_QUERY_PARAM = "tenant";
const MISSING_TENANT_CACHE_KEY = "__missing_tenant__";

function encoded(value: string) {
  return encodeURIComponent(value);
}

/** El tenant viaja como contexto seleccionado; DBI server-side conserva la autoridad. */
export function inspectionTenantRef(locator?: InspectionLocator): string | null {
  const explicit = locator?.tenantRef?.trim();
  if (explicit) return explicit;

  if (typeof window === "undefined") return null;
  const fromQuery = new URLSearchParams(window.location.search)
    .get(TENANT_QUERY_PARAM)
    ?.trim();
  return fromQuery || null;
}

function requireInspectionTenantRef(locator: InspectionLocator): string {
  const tenantRef = inspectionTenantRef(locator);
  if (!tenantRef) {
    throw new Error(
      "La captura INSPECT requiere un tenant DBI explícito mediante ?tenant=<tenant_ref>.",
    );
  }
  return tenantRef;
}

export function inspectionPlotKey(locator: InspectionLocator) {
  const tenantRef = inspectionTenantRef(locator) ?? MISSING_TENANT_CACHE_KEY;
  return [tenantRef, locator.organizationRef, locator.farmId, locator.plotId]
    .map(encoded)
    .join("|");
}

function observationUrl(locator: InspectionLocator) {
  return [
    "/api/v1/dbi/organizations",
    encoded(locator.organizationRef),
    "farms",
    encoded(locator.farmId),
    "plots",
    encoded(locator.plotId),
    "field-observations",
  ].join("/");
}

export function createInspectionOutboxAction(
  locator: InspectionLocator,
  observation: InspectionFieldObservationBody,
): InspectionOutboxAction {
  const tenantRef = requireInspectionTenantRef(locator);
  const now = new Date().toISOString();
  const observationId = crypto.randomUUID();
  const versionId = crypto.randomUUID();
  const scopedLocator = { ...locator, tenantRef };
  return {
    actionId: crypto.randomUUID(),
    plotKey: inspectionPlotKey(scopedLocator),
    tenantRef,
    locator: scopedLocator,
    observationId,
    versionId,
    request: { observation },
    state: "pending",
    createdAt: now,
    updatedAt: now,
    attemptCount: 0,
    lastError: null,
  };
}

export async function sendInspectionOutboxAction(
  action: InspectionOutboxAction,
): Promise<InspectionVersion> {
  const tenantRef = action.tenantRef?.trim();
  if (!tenantRef) {
    throw new Error("La observación offline no contiene un tenant DBI explícito.");
  }
  if (!action.observationId || !action.versionId) {
    throw new Error("La observación offline perdió su identidad idempotente.");
  }

  const { data } = await api.post<InspectionVersion>(
    observationUrl(action.locator),
    action.request,
    {
      headers: {
        "X-DBI-Tenant": tenantRef,
        "X-DBI-Observation-Id": action.observationId,
        "X-DBI-Version-Id": action.versionId,
      },
    },
  );
  return data;
}
