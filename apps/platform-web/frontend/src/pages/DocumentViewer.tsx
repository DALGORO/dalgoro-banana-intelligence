import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, Link, useLocation } from "react-router-dom";
import { api } from "../app/api";

function filenameFromDisposition(dispo?: string, fallback = "documento.bin") {
  if (!dispo) return fallback;
  const m = dispo.match(/filename\*=(?:UTF-8'')?([^;]+)|filename="?([^"]+)"?/i);
  let raw = (m?.[1] || m?.[2] || "").trim();
  try {
    raw = decodeURIComponent(raw);
  } catch {}
  return (raw || fallback).replace(/[/\\]+/g, "_");
}

type LoadedDoc = {
  blob: Blob;
  url: string;
  filename: string;
  mime: string;
};

export default function DocumentViewer() {
  const { docId } = useParams();
  const location = useLocation();

  const [loaded, setLoaded] = useState<LoadedDoc | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const routeTitle = (location.state as any)?.title || "Documento";

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    const loadDocument = async () => {
      setLoading(true);
      setErr(null);

      try {
        const res = await api.get(`/api/v1/documents/${docId}/stream`, {
          responseType: "blob",
        });

        const H: any = res?.headers;
        const get = (k: string) =>
          (typeof H?.get === "function" ? H.get(k.toLowerCase()) : H?.[k.toLowerCase()]) ||
          (typeof H?.get === "function" ? H.get(k) : H?.[k]) ||
          undefined;

        const dispo = get("Content-Disposition");
        const ct = get("Content-Type") || "application/octet-stream";

        let fallback = "documento.bin";
        if (String(ct).includes("spreadsheetml.sheet")) fallback = "documento.xlsx";
        else if (String(ct).includes("wordprocessingml.document")) fallback = "documento.docx";
        else if (String(ct).includes("pdf")) fallback = "documento.pdf";

        let filename = filenameFromDisposition(dispo, fallback);

        if (!dispo) {
          if (String(ct).includes("spreadsheetml.sheet") && !filename.endsWith(".xlsx")) {
            filename = filename.replace(/\.[^.]+$/, "") + ".xlsx";
          } else if (String(ct).includes("wordprocessingml.document") && !filename.endsWith(".docx")) {
            filename = filename.replace(/\.[^.]+$/, "") + ".docx";
          } else if (String(ct).includes("pdf") && !filename.endsWith(".pdf")) {
            filename = filename.replace(/\.[^.]+$/, "") + ".pdf";
          }
        }

        const blob = new Blob([res.data], { type: ct });
        objectUrl = URL.createObjectURL(blob);

        if (!active) {
          URL.revokeObjectURL(objectUrl);
          return;
        }

        setLoaded({
          blob,
          url: objectUrl,
          filename,
          mime: String(ct),
        });
      } catch (e: any) {
        if (!active) return;
        setErr(e?.response?.data?.detail ?? "No se pudo abrir el documento.");
      } finally {
        if (active) setLoading(false);
      }
    };

    loadDocument();

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId]);

  const isPdf = useMemo(() => {
    return !!loaded?.mime && loaded.mime.toLowerCase().includes("pdf");
  }, [loaded]);

  const handleDownload = useCallback(() => {
    if (!loaded) return;

    const a = document.createElement("a");
    a.href = loaded.url;
    a.download = loaded.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }, [loaded]);

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">Visualización documental</span>
          <h1>{routeTitle}</h1>
          <p className="page-subtitle">
            Revisa el documento generado o descárgalo para abrirlo en su aplicación correspondiente.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Link to={-1 as any} className="btn-secondary">
            ← Volver
          </Link>

          <button
            onClick={handleDownload}
            disabled={!loaded}
            className={loaded ? "btn-primary" : "btn opacity-60 cursor-not-allowed"}
          >
            Descargar
          </button>
        </div>
      </div>

      {loading && (
        <div className="card">
          <p className="muted">Cargando documento…</p>
        </div>
      )}

      {!loading && err && (
        <div className="status-banner status-banner-danger text-sm">
          {err}
        </div>
      )}

      {!loading && !err && loaded && isPdf && (
        <div className="surface p-2 overflow-hidden">
          <iframe
            src={loaded.url}
            title={loaded.filename}
            className="w-full h-[80vh] rounded-xl bg-white"
          />
        </div>
      )}

      {!loading && !err && loaded && !isPdf && (
        <div className="surface space-y-3">
          <div>
            <h2 className="text-lg">Vista previa no disponible</h2>
            <p className="muted mt-1">
              Este formato todavía no se puede mostrar directamente dentro del sistema.
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="metric-card">
              <p className="muted text-sm">Archivo</p>
              <p className="mt-2 font-medium text-slate-900 dark:text-white break-all">
                {loaded.filename}
              </p>
            </div>

            <div className="metric-card">
              <p className="muted text-sm">Formato detectado</p>
              <p className="mt-2 font-medium text-slate-900 dark:text-white break-all">
                {loaded.mime}
              </p>
            </div>
          </div>

          <div className="status-banner status-banner-info text-sm">
            Usa <strong>Descargar</strong> para abrir el archivo en Excel, Word u otra aplicación compatible.
          </div>
        </div>
      )}
    </div>
  );
}