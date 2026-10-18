import { useRef, useState } from "react";
import {
  inventoryFolder,
  type AnalysisFolderKind,
  type FolderFileMetadata,
  type FolderInventory,
} from "@/features/analysisFolderInventory";

/** Propiedades del selector de directorios en navegadores compatibles. */
const directoryPicker = { webkitdirectory: "", directory: "" };

function FolderSummary({ inventory }: { inventory: FolderInventory | null }) {
  if (!inventory) return <p className="text-xs text-slate-500">Sin carpeta seleccionada.</p>;
  return (
    <div className="space-y-2 text-xs">
      <p role="status" className="font-medium">
        {inventory.rootName ?? "Carpeta no reconocida"} · {inventory.totalFiles} archivos
      </p>
      <p className="muted">
        {inventory.candidateCount} candidatos por nombre · {inventory.reviewCount} requieren clasificación ·
        {" "}{inventory.excludedCount} complementarios o no reconocidos
      </p>
      {inventory.missing.length > 0 && (
        <p className="rounded-lg border border-amber-300/60 p-2" role="alert">
          No encontrados: {inventory.missing.join(", ")}. No se fabricarán capas faltantes.
        </p>
      )}
      {inventory.issues.length > 0 && (
        <ul className="list-disc pl-5 text-amber-700 dark:text-amber-300">
          {inventory.issues.slice(0, 6).map((issue, i) => <li key={i}>{issue}</li>)}
        </ul>
      )}
      <details className="rounded-lg border border-slate-300/40 p-2">
        <summary className="cursor-pointer font-semibold">Ver inventario de archivos</summary>
        <ul className="mt-2 max-h-56 space-y-2 overflow-y-auto">
          {inventory.entries.slice(0, 40).map((entry, i) => (
            <li className="border-b border-slate-300/30 pb-2" key={entry.path + i}>
              <strong>{entry.role}</strong> · {entry.status === "candidate" ? "Candidato" : "Revisión pendiente"}
              <span className="block break-all">{entry.path}</span>
              <span className="muted block">{entry.note}</span>
            </li>
          ))}
        </ul>
        {inventory.entries.length > 40 && (
          <p className="muted mt-2">Se muestran 40 de {inventory.entries.length} rutas. El inventario completo permanece solo en este navegador.</p>
        )}
      </details>
    </div>
  );
}

/** Solo MANAGE ve este inventario; la inspección no llama a ninguna API. */
export function AdminAnalysisFolderPanel() {
  const [folders, setFolders] = useState<Record<AnalysisFolderKind, FolderInventory | null>>({
    geospatial: null, multispectral: null,
  });
  const geoInput = useRef<HTMLInputElement>(null);
  const multiInput = useRef<HTMLInputElement>(null);

  function selectFolder(kind: AnalysisFolderKind, list: FileList | null) {
    const metadata: FolderFileMetadata[] = Array.from(list ?? [], file => ({
      name: file.name, size: file.size, webkitRelativePath: file.webkitRelativePath,
    }));
    setFolders(current => ({ ...current, [kind]: inventoryFolder(kind, metadata) }));
  }

  function clear() {
    setFolders({ geospatial: null, multispectral: null });
    if (geoInput.current) geoInput.current.value = "";
    if (multiInput.current) multiInput.current.value = "";
  }

  return (
    <section className="space-y-3 rounded-xl border border-slate-300/60 p-3 dark:border-slate-600"
      aria-label="Inventario local de dos carpetas de análisis">
      <div>
        <h3 className="text-sm font-semibold">Paso 1 · Reconocer dos carpetas de análisis</h3>
        <p className="muted mt-1 text-xs">
          Selecciona cada carpeta una vez. Solo se examinan nombres y rutas locales:
          no se leen ni envían los archivos, y no se aprueba ninguna publicación.
        </p>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
          <label htmlFor="dbi-folder-geospatial" className="block text-sm font-medium">
            Carpeta 1 · Análisis geoespacial
          </label>
          <input ref={geoInput} id="dbi-folder-geospatial" type="file" multiple
            {...directoryPicker} className="block w-full text-xs"
            onChange={event => selectFolder("geospatial", event.currentTarget.files)} />
          <FolderSummary inventory={folders.geospatial} />
        </div>
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
          <label htmlFor="dbi-folder-multispectral" className="block text-sm font-medium">
            Carpeta 2 · Análisis multiespectral
          </label>
          <input ref={multiInput} id="dbi-folder-multispectral" type="file" multiple
            {...directoryPicker} className="block w-full text-xs"
            onChange={event => selectFolder("multispectral", event.currentTarget.files)} />
          <FolderSummary inventory={folders.multispectral} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="muted text-xs">
          Inventario local, no validación científica. La carga segura, vista previa y aprobación
          se añadirán en las siguientes etapas.
        </p>
        <button type="button" className="btn-secondary" onClick={clear}
          disabled={!folders.geospatial && !folders.multispectral}>
          Limpiar selección
        </button>
      </div>
    </section>
  );
}
