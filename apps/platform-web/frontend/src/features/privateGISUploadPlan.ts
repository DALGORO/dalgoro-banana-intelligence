/** Plan de recepción PRIVADA: solo GIS originales y solo a través de la ruta existente.
 * No acepta RGB, rasters científicos, QML, GeoJSON ni PDFs. No publica capas.
 */
import type { FolderFileMetadata, FolderInventory } from "@/features/analysisFolderInventory";

export const MAX_PRIVATE_GIS_SIZE = 30 * 1024 * 1024;
export const MAX_PRIVATE_GIS_BATCH = 8;

export type PrivateGISUploadCandidate = {
  path: string;
  filename: string;
  size: number;
  kind: "gpkg" | "shp_zip";
};

export type PrivateGISUploadPlan = {
  candidates: PrivateGISUploadCandidate[];
  blockers: string[];
  ready: boolean;
};

export function planPrivateGISUpload(
  inventory: FolderInventory | null,
  files: readonly FolderFileMetadata[],
): PrivateGISUploadPlan {
  const blockers: string[] = [];
  if (!inventory || inventory.kind !== "geospatial" || !inventory.rootName) {
    return { candidates: [], blockers: ["Selecciona una carpeta geoespacial válida."], ready: false };
  }
  if (inventory.issues.length > 0 || inventory.totalFiles !== files.length) {
    return { candidates: [], blockers: ["El inventario tiene errores o no corresponde a los archivos seleccionados."], ready: false };
  }
  const byPath = new Map(files.map(file => [file.webkitRelativePath, file]));
  const candidates: PrivateGISUploadCandidate[] = [];
  for (const entry of inventory.entries) {
    if (!["GeoPackage", "Archivo GIS comprimido"].includes(entry.role)) continue;
    const source = byPath.get(entry.path);
    if (!source || !entry.path.startsWith(inventory.rootName + "/")
      || source.name !== entry.path.split("/").at(-1)) {
      blockers.push("Hay un archivo sin correspondencia exacta con el inventario.");
      continue;
    }
    const kind = entry.role === "GeoPackage" ? "gpkg" : "shp_zip";
    if (!source.name.toLowerCase().endsWith(kind === "gpkg" ? ".gpkg" : ".zip")) {
      blockers.push("Extensión no corresponde al formato GIS reconocido.");
    } else if (!Number.isSafeInteger(source.size) || source.size < 1 || source.size > MAX_PRIVATE_GIS_SIZE) {
      blockers.push(`${entry.path}: vacío o supera 30 MiB; no se enviará.`);
    } else if (source.name.length > 100) {
      blockers.push(`${entry.path}: nombre mayor de 100 caracteres.`);
    } else {
      candidates.push({ path: entry.path, filename: source.name, size: source.size, kind });
    }
  }
  if (!candidates.length) blockers.push("No hay originales GPKG/SHP ZIP compatibles en la carpeta 1.");
  if (candidates.length > MAX_PRIVATE_GIS_BATCH) {
    blockers.push(`Máximo ${MAX_PRIVATE_GIS_BATCH} originales por lote; divide la importación.`);
  }
  // Un plan parcial NO es enviable: nunca ocultar una fuente rechazada mientras
  // el administrador cree que envió todos los GIS reconocidos.
  return { candidates, blockers, ready: blockers.length === 0 };
}
