import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/app/api";
import DbiDensityPage from "./DbiDensityPage";

type DensityJobLite = {
  job_id: string;
  campaign_id: string | null;
  status: string;
  report_ready: boolean;
};

type CampaignAdoptionStatus = {
  job_id: string;
  eligible: boolean;
  adopted: boolean;
  campaign_id: string | null;
  campaign_status: string | null;
  campaign_origin: string | null;
  catalog_artifact_count: number;
  catalog_artifact_types: string[];
  message: string;
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
  const [adoption, setAdoption] = useState<CampaignAdoptionStatus | null>(null);
  const [campaignBusy, setCampaignBusy] = useState(false);
  const [campaignMessage, setCampaignMessage] = useState<string | null>(null);
  const [campaignError, setCampaignError] = useState<string | null>(null);
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
    if (!latest) {
      setAdoption(null);
      setReview(null);
      return;
    }

    const { data: campaignStatus } = await api.get<CampaignAdoptionStatus>(
      `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${latest.job_id}/campaign-adoption`,
    );
    setAdoption(campaignStatus);

    if (latest.status !== "completed") {
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

  const adoptHistoricalCampaign = async () => {
    if (!job || !adoption?.eligible) return;
    setCampaignBusy(true);
    setCampaignError(null);
    setCampaignMessage(null);
    try {
      const { data } = await api.post<CampaignAdoptionStatus>(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${job.job_id}/campaign-adoption`,
      );
      setAdoption(data);
      setCampaignMessage(data.message);
      await refresh();
    } catch (adoptionError) {
      setCampaignError(
        errorText(adoptionError, "No se pudo adoptar el trabajo histórico en Campaign."),
      );
    } finally {
      setCampaignBusy(false);
    }
  };

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
  const campaignOriginLabel = adoption?.campaign_origin === "legacy_import"
    ? "Trabajo histórico adoptado"
    : "Análisis nativo Campaign";

  return (
    <div className="space-y-5">
      <DbiDensityPage key={`${job?.job_id ?? "none"}:${job?.campaign_id ?? "historical"}`} />

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Trazabilidad Campaign</div>
          <h2 className="text-lg font-semibold">Continuidad del análisis histórico</h2>
          <p className="muted mt-1 text-sm">
            Permite incorporar un análisis completado antes de Campaign a la arquitectura DBI actual sin volver a ejecutar YOLO ni ninguna de las 17 etapas científicas.
          </p>
        </div>

        {!job && (
          <div className="status-banner status-banner-info text-sm">
            La trazabilidad Campaign aparecerá cuando exista un trabajo de densidad.
          </div>
        )}

        {job && adoption?.eligible && (
          <div className="space-y-3">
            <div className="status-banner status-banner-warning text-sm">
              <strong>Trabajo histórico detectado.</strong> La adopción crea una Campaign de compatibilidad, conserva el Job {job.job_id.slice(0, 8)}… y registra únicamente evidencia canónica verificable. No recalcula resultados ni modifica el motor de Density.
            </div>
            <button
              className="btn-primary"
              disabled={campaignBusy}
              onClick={() => void adoptHistoricalCampaign()}
            >
              {campaignBusy ? "Adoptando en Campaign…" : "Adoptar trabajo histórico en Campaign"}
            </button>
          </div>
        )}

        {job && adoption?.campaign_id && (
          <div className="status-banner status-banner-success text-sm">
            <div><strong>Campaign DBI:</strong> {adoption.campaign_id}</div>
            <div className="mt-1"><strong>Estado:</strong> {adoption.campaign_status ?? "Sin estado"}</div>
            <div className="mt-1"><strong>Origen:</strong> {campaignOriginLabel}</div>
            <div className="mt-1">
              <strong>Catálogo técnico:</strong> {adoption.catalog_artifact_count} evidencia{adoption.catalog_artifact_count === 1 ? "" : "s"} verificable{adoption.catalog_artifact_count === 1 ? "" : "s"}
              {adoption.catalog_artifact_types.length > 0 ? ` · ${adoption.catalog_artifact_types.join(", ")}` : ""}
            </div>
          </div>
        )}

        {campaignMessage && <div className="status-banner status-banner-success">{campaignMessage}</div>}
        {campaignError && <div className="status-banner status-banner-danger">{campaignError}</div>}
      </section>

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