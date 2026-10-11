import type { PlotMapTimelineLocator } from "./mapTimeline";

/** Respuesta READ existente: GET field-observations/{observation_id}. */
export type INSPECTObservedNumber = {
  state: "observed" | "not_measured" | "not_applicable";
  value: number | null;
  reason: string | null;
};

export type INSPECTReadVersion = {
  schema_version: "dbi-field-observation.v1";
  observation_id: string;
  version_id: string;
  version: number;
  created_at: string;
  payload: {
    tenant_ref: string;
    organization_ref: string;
    farm_id: string;
    plot_id: string;
    observed_at: string;
    evidence_kind: "observed";
    sampling_point_id: string | null;
    up_id: string | null;
    gps_fix: { accuracy_m: number } | null;
    core: {
      foure: INSPECTObservedNumber;
      yls: INSPECTObservedNumber;
      functional_leaves: INSPECTObservedNumber;
    };
  };
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isObservationUUID(value: string): boolean {
  return UUID_RE.test(value.trim());
}

/**
 * Rechazo adicional del lado cliente; NUNCA reemplaza autorización READ de API.
 * Respuesta por ID exacto, no coincidencia por fecha/cercanía/UP/índice.
 */
export function inspectionVersionMatchesScope(
  value: INSPECTReadVersion,
  locator: PlotMapTimelineLocator,
  requestedId: string,
): boolean {
  return Boolean(
    isObservationUUID(requestedId)
    && value?.schema_version === "dbi-field-observation.v1"
    && value?.observation_id?.toLowerCase() === requestedId.trim().toLowerCase()
    && isObservationUUID(value.version_id)
    && Number.isSafeInteger(value.version) && value.version >= 1
    && value.payload?.evidence_kind === "observed"
    && value.payload.tenant_ref === locator.tenantRef
    && value.payload.organization_ref === locator.organizationRef
    && value.payload.farm_id.toLowerCase() === locator.farmId.toLowerCase()
    && value.payload.plot_id.toLowerCase() === locator.plotId.toLowerCase()
    && Boolean(value.payload.core?.foure)
    && Boolean(value.payload.core?.yls)
    && Boolean(value.payload.core?.functional_leaves)
  );
}

export function observedNumberLabel(field: INSPECTObservedNumber): string {
  if (field?.state === "not_measured") return "No medido";
  if (field?.state === "not_applicable") return "No aplicable";
  if (field?.state !== "observed") return "Dato no disponible";
  return typeof field.value === "number" && Number.isFinite(field.value)
    ? field.value.toLocaleString("es-EC", { maximumFractionDigits: 2 })
    : "Dato no disponible";
}
