import { useRef, useState } from "react";
import type { PlotMapTimelineLocator } from "@/features/mapTimeline";
import { listGISImports, stageGISOriginal, type GISImportReceipt, type VectorCampaign } from "@/features/portalVectors";
import { planPrivateGISUpload } from "@/features/privateGISUploadPlan";
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
export function AdminAnalysisFolderPanel({
  locator, campaigns, onImportsRefreshed,
}: {
  locator: PlotMapTimelineLocator;
  campaigns: VectorCampaign[];
  onImportsRefreshed: (receipts: GISImportReceipt[]) => void;
}) {
  const geoFilesRef = useRef<File[]>([]);
  const busyRef = useRef(false);
  const [chosenCampaign, setChosenCampaign] = useState("");
  const [busy, setBusy] = useState(false);
  const [completed, setCompleted] = useState(0);
  const [uploadedPaths, setUploadedPaths] = useState<string[]>([]);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [folders, setFolders] = useState<Record<AnalysisFolderKind, FolderInventory | null>>({
    geospatial: null, multispectral: null,
  });
  const geoInput = useRef<HTMLInputElement>(null);
  const multiInput = useRef<HTMLInputElement>(null);

  function selectFolder(kind: AnalysisFolderKind, list: FileList | null) {
    const metadata: FolderFileMetadata[] = Array.from(list ?? [], file => ({
      name: file.name, size: file.size, webkitRelativePath: file.webkitRelativePath,
    }));
    if (kind === "geospatial") {
      geoFilesRef.current = Array.from(list ?? []);
      setUploadedPaths([]);
      setCompleted(0);
      setUploadMessage(null);
    }
    setFolders(current => ({ ...current, [kind]: inventoryFolder(kind, metadata) }));
  }

  const uploadPlan = planPrivateGISUpload(folders.geospatial, geoFilesRef.current);
  const allowedCampaigns = campaigns.filter(c => c.status !== "APPROVED" && c.status !== "PUBLISHED");
  const campaignAllowed = allowedCampaigns.some(c => c.id === chosenCampaign);
  const remaining = uploadPlan.candidates.filter(c => !uploadedPaths.includes(c.path));

  async function uploadPrivateGIS() {
    if (busyRef.current || !uploadPlan.ready || !campaignAllowed || remaining.length === 0) return;
    busyRef.current = true;
    setBusy(true);
    setCompleted(0);
    setUploadMessage(null);
    const sourceMap = new Map(geoFilesRef.current.map(file => [file.webkitRelativePath, file]));
    const uploadedNow: string[] = [];
    try {
      // Sin idempotencia persistente no re-subir originales de igual nombre.
      const existingReceipts = await listGISImports(locator);
      const previousNames = new Set(
        existingReceipts.filter(item => item.campaign_id === chosenCampaign)
          .map(item => item.original_filename.toLowerCase()),
      );
      for (const [i, candidate] of remaining.entries()) {
        if (previousNames.has(candidate.filename.toLowerCase())) {
          throw new Error(`${candidate.filename}: ya existe una recepción con este nombre en el levantamiento. Revisa el recibo antes de repetir.`);
        }
        const source = sourceMap.get(candidate.path);
        if (!source || source.size !== candidate.size || source.name !== candidate.filename) {
          throw new Error("La selección cambió: vuelve a seleccionar la carpeta.");
        }
        // "other" intencional: un nombre GPKG/ZIP no acredita density/plants/boundaries.
        await stageGISOriginal(
          locator, source, chosenCampaign, "other",
          candidate.filename.replace(/\.(gpkg|zip)$/i, "").trim().slice(0, 100),
        );
        uploadedNow.push(candidate.path);
        previousNames.add(candidate.filename.toLowerCase());
        setCompleted(i + 1);
      }
      setUploadMessage(`${uploadedNow.length} originales GIS recibidos en privado. Pendientes de conversión, revisión y aprobación; el cliente no los ve.`);
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } }; message?: string });
      setUploadMessage(typeof detail.response?.data?.detail === "string"
        ? detail.response.data.detail : detail.message || "La carga GIS se detuvo. Revisa la recepción antes de reintentar.");
    } finally {
      if (uploadedNow.length) {
        setUploadedPaths(previous => [...previous, ...uploadedNow]);
        try {
          const receipts = await listGISImports(locator);
          onImportsRefreshed(receipts);
        } catch {
          setUploadMessage("Carga privada recibida, pero no fue posible actualizar la lista. Consulta «Archivos GIS y estado de revisión» antes de repetir.");
        }
      }
      setBusy(false);
      busyRef.current = false;
    }
  }

  function clear() {
    if (busyRef.current) return;
    geoFilesRef.current = [];
    setChosenCampaign("");
    setUploadedPaths([]);
    setCompleted(0);
    setUploadMessage(null);
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
          Selecciona cada carpeta una vez. Primero se examinan solo nombres y rutas locales.
          El envío requiere pulsar «Guardar originales GIS» y jamás publica capas.
        </p>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
          <label htmlFor="dbi-folder-geospatial" className="block text-sm font-medium">
            Carpeta 1 · Análisis geoespacial
          </label>
          <input ref={geoInput} id="dbi-folder-geospatial" type="file" multiple
            {...directoryPicker} className="block w-full text-xs" disabled={busy}
            onChange={event => selectFolder("geospatial", event.currentTarget.files)} />
          <FolderSummary inventory={folders.geospatial} />
        </div>
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
          <label htmlFor="dbi-folder-multispectral" className="block text-sm font-medium">
            Carpeta 2 · Análisis multiespectral
          </label>
          <input ref={multiInput} id="dbi-folder-multispectral" type="file" multiple
            {...directoryPicker} className="block w-full text-xs" disabled={busy}
            onChange={event => selectFolder("multispectral", event.currentTarget.files)} />
          <FolderSummary inventory={folders.multispectral} />
        </div>
      </div>
      <section className="space-y-3 rounded-lg border border-slate-300/60 p-3 dark:border-slate-600"
        aria-label="Guardar originales GIS de la carpeta 1 en almacenamiento privado">
        <h4 className="text-sm font-semibold">Paso 2 · Guardar originales GIS privados</h4>
        <p className="muted text-xs">
          Solo se pueden recibir archivos GeoPackage o ZIP GIS de hasta 30 MiB,
          detectados en la carpeta 1. Las ortofotos, índices COG, QML y PDF
          todavía requieren un cargador científico independiente.
        </p>
        <label className="block text-xs font-medium" htmlFor="dbi-folder-private-campaign">
          Levantamiento técnico real que recibirá los archivos
        </label>
        <select className="w-full rounded-lg border p-2 text-sm dark:bg-slate-900"
          id="dbi-folder-private-campaign" value={chosenCampaign} disabled={busy}
          onChange={event => { setChosenCampaign(event.target.value); setUploadedPaths([]); setCompleted(0); setUploadMessage(null); }}>
          <option value="">Seleccionar levantamiento antes de cargar</option>
          {allowedCampaigns.map(c => (
            <option key={c.id} value={c.id}>{c.name} · {c.captured_at.slice(0, 10)}</option>
          ))}
        </select>
        {uploadPlan.blockers.length > 0 && folders.geospatial && (
          <ul role="alert" className="list-disc pl-5 text-xs text-amber-700 dark:text-amber-300">
            {uploadPlan.blockers.map((issue, i) => <li key={i}>{issue}</li>)}
          </ul>
        )}
        {uploadPlan.ready && (
          <div className="space-y-1 text-xs">
            <strong>{uploadPlan.candidates.length} originales GIS reconocidos</strong>
            <ul className="max-h-32 list-disc overflow-y-auto pl-5">
              {uploadPlan.candidates.map(item => (
                <li key={item.path} className="break-all">
                  {item.path} · {item.kind === "gpkg" ? "GeoPackage" : "ZIP GIS"}
                  {uploadedPaths.includes(item.path) ? " · Recibido en privado" : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
        <button className="btn-primary w-full" type="button"
          disabled={busy || !campaignAllowed || !uploadPlan.ready || remaining.length === 0}
          onClick={() => void uploadPrivateGIS()}>
          {busy ? `Guardando originales (${completed}/${remaining.length})…`
            : remaining.length === 0 && uploadedPaths.length > 0
              ? "Originales GIS recibidos; pendientes de revisión"
              : `Guardar ${remaining.length} original(es) en privado`}
        </button>
        {uploadMessage && <p role="status" className="text-xs">{uploadMessage}</p>}
        <p className="muted text-xs">
          No publica: cada fuente queda sujeta al worker de conversión, vista previa
          privada y aprobación posterior. No se clasifica el tipo de capa por su nombre.
        </p>
      </section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="muted text-xs">
          El inventario no valida resultados científicos. Los COG, estilos QML y PDF
          requieren un cargador posterior; la vista previa y aprobación siguen separadas.
        </p>
        <button type="button" className="btn-secondary" onClick={clear}
          disabled={busy || (!folders.geospatial && !folders.multispectral)}>
          Limpiar selección
        </button>
      </div>
    </section>
  );
}
