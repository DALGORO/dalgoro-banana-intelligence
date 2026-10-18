/** H14: contrato LOCAL de preparación de dos carpetas.
 * Exportar este borrador NO equivale a certificar, subir, aprobar ni publicar.
 */
import {
  INDEX_REFS, type FolderFileMetadata, type FolderInventory, type IndexRef,
} from "./analysisFolderInventory.ts";
import type { PlotMapTimelineLocator } from "./mapTimeline";

export type ScientificDraftFile = {
  folder: "geospatial" | "multispectral";
  role: "rgb" | "scientific_cog" | "qml_style";
  index: IndexRef | null;
  relative_path: string;
  size_bytes: number;
  sha256: null;
  file_content_verified: false;
};

export type ScientificReceptionDraft = {
  schema_version: "dbi-h14-scientific-reception-draft.v1";
  state: "local_metadata_only_not_uploaded";
  scope: {
    tenant_ref: string; organization_ref: string; farm_id: string;
    plot_id: string; campaign_id: string;
  };
  folders: { geospatial: string | null; multispectral: string | null };
  files: ScientificDraftFile[];
  blockers: string[];
  structural_ready: boolean;
  scientific_validated: false;
  server_received: false;
  institutional_approved: false;
  published: false;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function prepareScientificReceptionDraft(
  locator: PlotMapTimelineLocator,
  campaignId: string,
  geo: FolderInventory | null,
  multi: FolderInventory | null,
  geoSources: readonly FolderFileMetadata[],
  multiSources: readonly FolderFileMetadata[],
): ScientificReceptionDraft {
  const blockers: string[] = [];
  const files: ScientificDraftFile[] = [];
  if (!locator || !locator.tenantRef?.trim() || !locator.organizationRef?.trim()
      || !UUID.test(locator.farmId ?? "") || !UUID.test(locator.plotId ?? "") || !UUID.test(campaignId)) {
    blockers.push("No existe un ámbito de organización, finca, lote y Campaign técnicamente identificable.");
  }
  const inputs = [
    ["geospatial", geo, geoSources],
    ["multispectral", multi, multiSources],
  ] as const;

  for (const [kind, inv, sources] of inputs) {
    if (!inv || inv.kind !== kind || !inv.rootName || inv.totalFiles !== sources.length || !sources.length) {
      blockers.push(`Carpeta ${kind}: selección incompleta o no coincide con el inventario.`);
      continue;
    }
    if (inv.issues.length) blockers.push(...inv.issues.map(issue => `${kind}: ${issue}`));
    if (kind === "multispectral" && inv.missing.length) {
      blockers.push(...inv.missing.map(label => `Multiespectral faltante: ${label}`));
    }
  }

  function add(kind: "geospatial" | "multispectral",
               inv: FolderInventory | null, sources: readonly FolderFileMetadata[],
               role: ScientificDraftFile["role"], index: IndexRef | null,
               entryRole: string): void {
    if (!inv?.rootName) return;
    const entries = inv.entries.filter(entry => entry.role === entryRole && entry.status === "candidate");
    if (entries.length !== 1) {
      blockers.push(`${entryRole}: se exige exactamente un candidato, encontrados ${entries.length}.`);
      return;
    }
    const entry = entries[0];
    const matching = sources.filter(src => src.webkitRelativePath === entry.path);
    if (matching.length !== 1
        || matching[0].name !== entry.path.split("/").at(-1)
        || !Number.isSafeInteger(matching[0].size) || matching[0].size <= 0
        || !entry.path.startsWith(inv.rootName + "/")) {
      blockers.push(`${entryRole}: archivo local ausente, vacío o ambiguo.`);
      return;
    }
    files.push({
      folder: kind, role, index, relative_path: entry.path,
      size_bytes: matching[0].size, sha256: null,
      file_content_verified: false,
    });
  }

  add("geospatial", geo, geoSources, "rgb", null, "Ortofoto RGB");
  for (const index of INDEX_REFS) {
    add("multispectral", multi, multiSources, "scientific_cog", index, `${index} · ráster científico`);
    add("multispectral", multi, multiSources, "qml_style", index, `${index} · estilo QML`);
  }
  if (geo?.entries.some(item => item.role === "Ráster sin tipo confirmado")) {
    blockers.push("Carpeta geoespacial: existen TIFF sin tipo confirmado; requieren clasificación manual.");
  }
  if (multi?.entries.some(item => item.role === "Índice ambiguo")) {
    blockers.push("Carpeta multiespectral: hay TIFF/QML sin identidad de índice inequívoca.");
  }
  const unique = new Set(files.map(file => file.folder + ":" + file.relative_path.toLowerCase()));
  if (unique.size !== files.length) blockers.push("El plan contiene rutas de archivo repetidas.");
  if (files.length !== 13) blockers.push("La recepción requiere 1 RGB, 6 COG y 6 estilos QML reconocidos.");
  return {
    schema_version: "dbi-h14-scientific-reception-draft.v1",
    state: "local_metadata_only_not_uploaded",
    scope: {
      tenant_ref: locator?.tenantRef ?? "", organization_ref: locator?.organizationRef ?? "",
      farm_id: locator?.farmId ?? "", plot_id: locator?.plotId ?? "",
      campaign_id: campaignId,
    },
    folders: { geospatial: geo?.rootName ?? null, multispectral: multi?.rootName ?? null },
    files,
    blockers,
    structural_ready: blockers.length === 0,
    scientific_validated: false, server_received: false,
    institutional_approved: false, published: false,
  };
}
