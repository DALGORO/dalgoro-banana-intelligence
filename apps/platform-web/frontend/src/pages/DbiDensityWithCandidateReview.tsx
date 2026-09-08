import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/app/api";
import DbiDensityPage from "./DbiDensityPage";

type DensityJobLite = {
  job_id: string;
  status: string;
  report_ready: boolean;
};

type CandidateReviewStatus = {
  available: boolean;
  candidates_ready: boolean;
  status: string;
  error: string | null;
  updated_at: string | null;
};

function errorText(error: unknown, fallback: string) {
  if (typeof error !== "object" || error === null) return fallback;
  const response = (error as { response?: { data?: { detail?: unknown } } }).response;
  return typeof response?.data?.detail === "string" ? response.data.detail : fallback;
}

export default function DbiDensityWithCandidateReview() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);
  const [job, setJob] = useState<DensityJobLite | null>(null);
  const [review, setReview] = useState<CandidateReviewStatus | null>(null);
  const [reviewFile, setReviewFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const { data: latest } = await api.get<DensityJobLite | null>(
      `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/latest`,
    );
    setJob(latest);
    if (!latest || latest.status !== "completed") {
      setReview(null);
      return;
    }
    const { data: reviewStatus } = await api.get<CandidateReviewStatus>(
      `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${latest.job_id}/candidate-review`,
    );
    setReview(reviewStatus);
  }, [companyId]);

  useEffect(() => {
    void refresh().catch(() => undefined);
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const downloadCandidates = async () => {
    if (!job || !review?.candidates_ready) return;
    setBusy("download");
    setError(null);
    try {
      const response = await api.get(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${job.job_id}/candidates`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(response.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `candidatos_siembra_${job.job_id.slice(0, 8)}.gpkg`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(errorText(downloadError, "No se pudo descargar la capa de candidatos."));
    } finally {
      setBusy(null);
    }
  };

  const incorporateReview = async () => {
    if (!job || !reviewFile) return;
    setBusy("review");
    setError(null);
    setMessage(null);
    const form = new FormData();
    form.append("reviewed_candidates", reviewFile);
    try {
      const { data } = await api.post<CandidateReviewStatus>(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${job.job_id}/candidate-review`,
        form,
      );
      setReview(data);
      setReviewFile(null);
      setMessage("Revisión recibida. DALGORO está regenerando prioridad, mapas e informe técnico.");
    } catch (reviewError) {
      setError(errorText(reviewError, "No se pudo incorporar la revisión de candidatos."));
    } finally {
      setBusy(null);
    }
  };

  const completed = job?.status === "completed";
  const reviewing = review?.status === "running";

  return (
    <div className="space-y-5">
      <DbiDensityPage />

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Revisión técnica posterior</div>
          <h2 className="text-lg font-semibold">Incorporar revisión de candidatos</h2>
          <p className="muted mt-1 text-sm">
            Reutiliza la función del motor local estable para depurar en QGIS los candidatos de siembra antes de emitir la versión técnica corregida del informe.
          </p>
        </div>

        {!completed && (
          <div className="status-banner status-banner-info text-sm">
            Esta función se habilita cuando el análisis completo termina y existe la capa de candidatos.
          </div>
        )}

        {completed && review && !review.available && (
          <div className="status-banner status-banner-warning text-sm">
            El motor local instalado no expone todavía el módulo de revisión de candidatos.
          </div>
        )}

        {completed && review?.available && (
          <>
            <div className="status-banner status-banner-warning text-sm">
              <strong>Regla de esta revisión:</strong> descarga el GeoPackage, elimina únicamente los candidatos falsos y conserva los puntos restantes sin moverlos ni crear candidatos nuevos. No cambies los identificadores de los candidatos. Al incorporarlo, DALGORO conserva YOLO, inventario, estadísticas, patrón espacial, densidad hexagonal y KDE; regenera priorización operativa, mapas e informe.
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
                <h3 className="font-semibold">1. Revisar en QGIS</h3>
                <p className="muted mt-1 text-sm">
                  Descarga la capa activa <code>candidatos_siembra.gpkg</code>, elimina los falsos candidatos y guarda el resultado como GeoPackage.
                </p>
                <button
                  className="btn-secondary mt-3"
                  disabled={busy !== null || reviewing || !review.candidates_ready}
                  onClick={() => void downloadCandidates()}
                >
                  {busy === "download" ? "Preparando GeoPackage…" : "Descargar candidatos GPKG"}
                </button>
              </div>

              <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
                <h3 className="font-semibold">2. Incorporar revisión</h3>
                <label className="mt-2 block text-sm">
                  <span className="font-medium">GeoPackage revisado</span>
                  <input
                    className="mt-2 block w-full"
                    type="file"
                    accept=".gpkg"
                    disabled={reviewing}
                    onChange={(event) => setReviewFile(event.target.files?.[0] ?? null)}
                  />
                </label>
                {reviewFile && <div className="chip mt-2">{reviewFile.name}</div>}
                <button
                  className="btn-primary mt-3"
                  disabled={busy !== null || reviewing || !reviewFile || !review.candidates_ready}
                  onClick={() => void incorporateReview()}
                >
                  {reviewing || busy === "review" ? "Incorporando revisión…" : "Incorporar revisión de candidatos"}
                </button>
              </div>
            </div>

            {review.status === "running" && (
              <div className="status-banner status-banner-info">
                Revisión en ejecución. Se están regenerando únicamente la priorización operativa, el paquete cartográfico y el informe técnico.
              </div>
            )}
            {review.status === "completed" && (
              <div className="status-banner status-banner-success">
                Revisión incorporada correctamente. Prioridad, mapas e informe fueron regenerados con trazabilidad de la revisión.
              </div>
            )}
            {review.status === "failed" && (
              <div className="status-banner status-banner-danger">
                {review.error ?? "La revisión de candidatos no pudo completarse."}
              </div>
            )}
          </>
        )}

        {message && <div className="status-banner status-banner-success">{message}</div>}
        {error && <div className="status-banner status-banner-danger">{error}</div>}
      </section>
    </div>
  );
}
