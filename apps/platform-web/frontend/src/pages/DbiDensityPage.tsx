import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/app/api";

type PilotContext = { tenant_ref: string; organization_ref: string };
type Company = { id: number; nombre?: string; name?: string };
type Farm = { id: string; code: string; name: string };
type Plot = { id: string; farm_id: string; code: string; name: string };
type Asset = {
  id: string;
  farm_id: string;
  plot_id: string | null;
  asset_kind: string;
  status: string;
  size_bytes: number;
  crs: string | null;
};
type DensityRuntime = { ready: boolean; message: string };
type DensityStage = { key: string; title: string; status: string; error: string | null };
type DensityJob = {
  job_id: string;
  campaign_id: string | null;
  status: string;
  progress_percent: number;
  stages: DensityStage[];
  report_ready: boolean;
  error: string | null;
};
type CreatedJob = { job_id: string; campaign_id: string | null; status: string };
type UploadedOrtho = { asset_id: string; size_bytes: number };

function errorText(error: unknown, fallback: string) {
  if (typeof error !== "object" || error === null) return fallback;
  const response = (error as { response?: { data?: { detail?: unknown } } }).response;
  return typeof response?.data?.detail === "string" ? response.data.detail : fallback;
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 2)} ${units[index]}`;
}

function stageLabel(value: string) {
  if (value === "completed") return "Completada";
  if (value === "running") return "En ejecución";
  if (value === "failed") return "Falló";
  return "Pendiente";
}

function stageClass(value: string) {
  if (value === "completed") return "status-banner status-banner-success";
  if (value === "running") return "status-banner status-banner-info";
  if (value === "failed") return "status-banner status-banner-danger";
  return "rounded-xl border border-slate-200 p-3 dark:border-white/10";
}

export default function DbiDensityPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);
  const [company, setCompany] = useState<Company | null>(null);
  const [context, setContext] = useState<PilotContext | null>(null);
  const [runtime, setRuntime] = useState<DensityRuntime | null>(null);
  const [farms, setFarms] = useState<Farm[]>([]);
  const [plotsByFarm, setPlotsByFarm] = useState<Record<string, Plot[]>>({});
  const [assetsByFarm, setAssetsByFarm] = useState<Record<string, Asset[]>>({});
  const [farmId, setFarmId] = useState("");
  const [plotId, setPlotId] = useState("");
  const [orthophotoAssetId, setOrthophotoAssetId] = useState("");
  const [farmCode, setFarmCode] = useState("FINCA-001");
  const [farmName, setFarmName] = useState("");
  const [plotCode, setPlotCode] = useState("LOTE-001");
  const [plotName, setPlotName] = useState("");
  const [orthoFile, setOrthoFile] = useState<File | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [boundarySheet, setBoundarySheet] = useState("Hoja1");
  const [targetDensity, setTargetDensity] = useState("1400");
  const [boundaryExcel, setBoundaryExcel] = useState<File | null>(null);
  const [exclusionsGpkg, setExclusionsGpkg] = useState<File | null>(null);
  const [job, setJob] = useState<DensityJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDbiData = useCallback(async (ctx: PilotContext) => {
    const config = { headers: { "X-DBI-Tenant": ctx.tenant_ref } };
    const { data: farmRows } = await api.get<Farm[]>(
      `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms`,
      config,
    );
    const nextFarms = Array.isArray(farmRows) ? farmRows : [];
    setFarms(nextFarms);
    const plots = await Promise.all(
      nextFarms.map(async (farm) => {
        const { data } = await api.get<Plot[]>(
          `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms/${farm.id}/plots`,
          config,
        );
        return [farm.id, Array.isArray(data) ? data : []] as const;
      }),
    );
    const assets = await Promise.all(
      nextFarms.map(async (farm) => {
        const { data } = await api.get<Asset[]>(
          `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms/${farm.id}/assets`,
          config,
        );
        return [farm.id, Array.isArray(data) ? data : []] as const;
      }),
    );
    setPlotsByFarm(Object.fromEntries(plots));
    setAssetsByFarm(Object.fromEntries(assets));
    setFarmId((current) =>
      current && nextFarms.some((farm) => farm.id === current) ? current : nextFarms[0]?.id ?? "",
    );
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        const [{ data: companyData }, { data: ctx }, { data: runtimeData }, { data: latestJob }] =
          await Promise.all([
            api.get<Company>(`/api/v1/companies/${companyId}`),
            api.post<PilotContext>(`/api/v1/dbi/pilot/companies/${companyId}/bootstrap`),
            api.get<DensityRuntime>(`/api/v1/dbi/pilot/companies/${companyId}/density/runtime`),
            api.get<DensityJob | null>(`/api/v1/dbi/pilot/companies/${companyId}/density/jobs/latest`),
          ]);
        if (!active) return;
        setCompany(companyData);
        setContext(ctx);
        setRuntime(runtimeData);
        setJob(latestJob);
        await loadDbiData(ctx);
      } catch (initialError) {
        if (active) setError(errorText(initialError, "No se pudo preparar el módulo de densidad."));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [companyId, loadDbiData]);

  useEffect(() => {
    const plots = plotsByFarm[farmId] ?? [];
    setPlotId((current) =>
      current && plots.some((plot) => plot.id === current) ? current : plots[0]?.id ?? "",
    );
  }, [farmId, plotsByFarm]);

  const verifiedOrthos = useMemo(
    () =>
      (assetsByFarm[farmId] ?? []).filter(
        (asset) =>
          asset.plot_id === plotId && asset.asset_kind === "orthophoto" && asset.status === "verified",
      ),
    [assetsByFarm, farmId, plotId],
  );

  useEffect(() => {
    setOrthophotoAssetId((current) =>
      current && verifiedOrthos.some((asset) => asset.id === current)
        ? current
        : verifiedOrthos[verifiedOrthos.length - 1]?.id ?? "",
    );
  }, [verifiedOrthos]);

  const refreshJob = useCallback(
    async (jobId: string) => {
      const { data } = await api.get<DensityJob>(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${jobId}`,
      );
      setJob(data);
      return data;
    },
    [companyId],
  );

  useEffect(() => {
    if (!job || job.status !== "running") return undefined;
    const timer = window.setInterval(() => {
      void refreshJob(job.job_id).catch((pollError) =>
        setError(errorText(pollError, "No se pudo actualizar el progreso del análisis.")),
      );
    }, 2500);
    return () => window.clearInterval(timer);
  }, [job, refreshJob]);

  const createFarm = async () => {
    if (!context || !farmCode.trim() || !farmName.trim()) {
      setError("Ingresa código y nombre de la finca.");
      return;
    }
    setBusy("farm");
    setError(null);
    setMessage(null);
    try {
      const { data } = await api.post<Farm>(
        `/api/v1/dbi/organizations/${encodeURIComponent(context.organization_ref)}/farms`,
        { code: farmCode.trim(), name: farmName.trim(), status: "active" },
        { headers: { "X-DBI-Tenant": context.tenant_ref } },
      );
      await api.post(`/api/v1/dbi/pilot/companies/${companyId}/bootstrap`);
      await loadDbiData(context);
      setFarmId(data.id);
      setFarmName("");
      setMessage("Finca creada. Ahora puedes crear el lote sin cargar GeoJSON.");
    } catch (createError) {
      setError(errorText(createError, "No se pudo crear la finca."));
    } finally {
      setBusy(null);
    }
  };

  const createPlot = async () => {
    if (!context || !farmId || !plotCode.trim() || !plotName.trim()) {
      setError("Selecciona una finca e ingresa código y nombre del lote.");
      return;
    }
    setBusy("plot");
    setError(null);
    setMessage(null);
    try {
      const { data } = await api.post<Plot>(
        `/api/v1/dbi/organizations/${encodeURIComponent(context.organization_ref)}/farms/${farmId}/plots`,
        { code: plotCode.trim(), name: plotName.trim(), status: "active" },
        { headers: { "X-DBI-Tenant": context.tenant_ref } },
      );
      await api.post(`/api/v1/dbi/pilot/companies/${companyId}/bootstrap`);
      await loadDbiData(context);
      setFarmId(data.farm_id);
      setPlotId(data.id);
      setPlotName("");
      setMessage("Lote creado sin GeoJSON. El límite del análisis se construirá desde el Excel.");
    } catch (createError) {
      setError(errorText(createError, "No se pudo crear el lote."));
    } finally {
      setBusy(null);
    }
  };

  const uploadOrthophoto = async () => {
    if (!context || !farmId || !plotId || !orthoFile) {
      setError("Selecciona finca, lote y la ortofoto GeoTIFF.");
      return;
    }
    setBusy("ortho");
    setError(null);
    setMessage(null);
    setUploadPct(0);
    const form = new FormData();
    form.append("farm_id", farmId);
    form.append("plot_id", plotId);
    form.append("crs", "AUTO_FROM_GEOTIFF");
    form.append("file", orthoFile);
    try {
      const { data } = await api.post<UploadedOrtho>(
        `/api/v1/dbi/pilot/companies/${companyId}/orthophoto`,
        form,
        {
          onUploadProgress: (event) => {
            if (event.total) {
              setUploadPct(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            }
          },
        },
      );
      await loadDbiData(context);
      setOrthophotoAssetId(data.asset_id);
      setOrthoFile(null);
      setUploadPct(100);
      setMessage(`Ortofoto verificada y lista para analizar · ${formatBytes(data.size_bytes)}.`);
    } catch (uploadError) {
      setError(errorText(uploadError, "No se pudo cargar la ortofoto."));
    } finally {
      setBusy(null);
    }
  };

  const execute = async () => {
    const density = Number(targetDensity);
    if (!runtime?.ready) return setError(runtime?.message ?? "El motor de densidad no está listo.");
    if (!farmId || !plotId || !orthophotoAssetId)
      return setError("Selecciona finca, lote y una ortofoto verificada.");
    if (!boundaryExcel || !boundarySheet.trim())
      return setError("Selecciona el Excel de coordenadas e indica la hoja.");
    if (!Number.isFinite(density) || density <= 0)
      return setError("La densidad objetivo debe ser mayor que cero.");

    const form = new FormData();
    form.append("farm_id", farmId);
    form.append("plot_id", plotId);
    form.append("orthophoto_asset_id", orthophotoAssetId);
    form.append("boundary_sheet", boundarySheet.trim());
    form.append("target_density", String(density));
    form.append("boundary_excel", boundaryExcel);
    if (exclusionsGpkg) form.append("exclusions_gpkg", exclusionsGpkg);

    setBusy("run");
    setError(null);
    setMessage(null);
    try {
      const { data } = await api.post<CreatedJob>(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs`,
        form,
      );
      await refreshJob(data.job_id);
      setMessage(
        data.campaign_id
          ? `Análisis completo iniciado. Campaign DBI ${data.campaign_id.slice(0, 8)}… vinculada; el motor ejecutará las 17 etapas automáticamente.`
          : "Análisis completo iniciado. El motor ejecutará las 17 etapas automáticamente.",
      );
    } catch (runError) {
      setError(errorText(runError, "No se pudo iniciar el análisis completo."));
    } finally {
      setBusy(null);
    }
  };

  const action = async (kind: "stop" | "resume") => {
    if (!job) return;
    setBusy(kind);
    setError(null);
    try {
      await api.post(`/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${job.job_id}/${kind}`);
      await refreshJob(job.job_id);
      setMessage(kind === "stop" ? "Ejecución detenida; puede reanudarse." : "Ejecución reanudada.");
    } catch (actionError) {
      setError(errorText(actionError, `No se pudo ${kind === "stop" ? "detener" : "reanudar"} la ejecución.`));
    } finally {
      setBusy(null);
    }
  };

  const downloadReport = async () => {
    if (!job?.report_ready) return;
    setBusy("report");
    setError(null);
    try {
      const response = await api.get(
        `/api/v1/dbi/pilot/companies/${companyId}/density/jobs/${job.job_id}/report`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(response.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `informe_densidad_${job.job_id.slice(0, 8)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(errorText(downloadError, "No se pudo descargar el informe técnico."));
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <div className="card">Preparando análisis de densidad…</div>;

  const selectedOrtho = verifiedOrthos.find((asset) => asset.id === orthophotoAssetId);
  const companyName = company?.nombre ?? company?.name ?? `Empresa ${companyId}`;

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">DALGORO Banana Intelligence · Densidad de siembra</span>
          <h1>{companyName}</h1>
          <p className="page-subtitle">
            Finca y lote → ortofoto → Excel de coordenadas → exclusiones opcionales → densidad objetivo → análisis completo → informe PDF.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="btn-secondary" to={`/companies/${companyId}/agricultura`}>
            INSPECT / preparación avanzada
          </Link>
          <Link className="btn-ghost" to={`/companies/${companyId}`}>← Empresa</Link>
        </div>
      </div>

      {error && <div className="status-banner status-banner-danger">{error}</div>}
      {message && <div className="status-banner status-banner-success">{message}</div>}
      <div className={runtime?.ready ? "status-banner status-banner-success" : "status-banner status-banner-warning"}>
        <strong>Motor de densidad:</strong> {runtime?.message ?? "Estado no disponible."}
      </div>
      <div className="status-banner status-banner-info text-sm">
        Para densidad de siembra no necesitas GeoJSON. DALGORO construye el límite de análisis desde el Excel de coordenadas y genera los archivos GIS requeridos durante el pipeline.
      </div>

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 1 · Preparación mínima</div>
          <h2 className="text-lg font-semibold">Finca, lote y ortofoto en esta misma pantalla</h2>
          <p className="muted mt-1 text-sm">
            Puedes reutilizar registros existentes o crear los necesarios aquí. El lote se crea sin polígono; el Excel definirá el área del análisis.
          </p>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
            <h3 className="font-semibold">1A. Finca</h3>
            <label className="mt-3 block text-sm">
              <span className="font-medium">Usar finca existente</span>
              <select className="mt-2 w-full" value={farmId} onChange={(event) => setFarmId(event.target.value)}>
                <option value="">Seleccionar finca</option>
                {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.code} · {farm.name}</option>)}
              </select>
            </label>
            <div className="mt-3 grid gap-2">
              <input value={farmCode} onChange={(event) => setFarmCode(event.target.value)} placeholder="FINCA-001" />
              <input value={farmName} onChange={(event) => setFarmName(event.target.value)} placeholder="Nombre de la finca" />
              <button className="btn-secondary" disabled={busy !== null || !context || !farmCode.trim() || !farmName.trim()} onClick={() => void createFarm()}>
                {busy === "farm" ? "Creando…" : "Crear finca"}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
            <h3 className="font-semibold">1B. Lote</h3>
            <label className="mt-3 block text-sm">
              <span className="font-medium">Usar lote existente</span>
              <select className="mt-2 w-full" value={plotId} onChange={(event) => setPlotId(event.target.value)}>
                <option value="">Seleccionar lote</option>
                {(plotsByFarm[farmId] ?? []).map((plot) => <option key={plot.id} value={plot.id}>{plot.code} · {plot.name}</option>)}
              </select>
            </label>
            <div className="mt-3 grid gap-2">
              <input value={plotCode} onChange={(event) => setPlotCode(event.target.value)} placeholder="LOTE-001" />
              <input value={plotName} onChange={(event) => setPlotName(event.target.value)} placeholder="Nombre del lote" />
              <button className="btn-secondary" disabled={busy !== null || !context || !farmId || !plotCode.trim() || !plotName.trim()} onClick={() => void createPlot()}>
                {busy === "plot" ? "Creando…" : "Crear lote sin GeoJSON"}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
            <h3 className="font-semibold">1C. Ortofoto</h3>
            <label className="mt-3 block text-sm">
              <span className="font-medium">Ortofoto verificada existente</span>
              <select className="mt-2 w-full" value={orthophotoAssetId} onChange={(event) => setOrthophotoAssetId(event.target.value)}>
                <option value="">Seleccionar ortofoto</option>
                {verifiedOrthos.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.id.slice(0, 8)}… · {formatBytes(asset.size_bytes)}
                  </option>
                ))}
              </select>
            </label>
            <label className="mt-3 block text-sm">
              <span className="font-medium">O cargar GeoTIFF desde la laptop</span>
              <input className="mt-2 block w-full" type="file" accept=".tif,.tiff,image/tiff" onChange={(event) => setOrthoFile(event.target.files?.[0] ?? null)} />
            </label>
            {orthoFile && <div className="chip mt-2">{orthoFile.name} · {formatBytes(orthoFile.size)}</div>}
            {uploadPct !== null && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-xs"><span>Carga</span><span>{uploadPct}%</span></div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                  <div className="h-full bg-slate-700 dark:bg-white" style={{ width: `${uploadPct}%` }} />
                </div>
              </div>
            )}
            <button className="btn-secondary mt-3" disabled={busy !== null || !context || !farmId || !plotId || !orthoFile} onClick={() => void uploadOrthophoto()}>
              {busy === "ortho" ? "Cargando y verificando…" : "Cargar y verificar ortofoto"}
            </button>
          </div>
        </div>
      </section>

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 2 · Entradas del análisis</div>
          <h2 className="text-lg font-semibold">Configurar densidad de siembra</h2>
          <p className="muted mt-1 text-sm">
            El sistema conserva automáticamente los parámetros técnicos de la instalación que ya funciona.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            <span className="font-medium">Finca seleccionada</span>
            <select className="mt-2 w-full" value={farmId} onChange={(event) => setFarmId(event.target.value)}>
              <option value="">Seleccionar finca</option>
              {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.code} · {farm.name}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">Lote seleccionado</span>
            <select className="mt-2 w-full" value={plotId} onChange={(event) => setPlotId(event.target.value)}>
              <option value="">Seleccionar lote</option>
              {(plotsByFarm[farmId] ?? []).map((plot) => <option key={plot.id} value={plot.id}>{plot.code} · {plot.name}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">Ortofoto GeoTIFF verificada</span>
            <select className="mt-2 w-full" value={orthophotoAssetId} onChange={(event) => setOrthophotoAssetId(event.target.value)}>
              <option value="">Seleccionar ortofoto</option>
              {verifiedOrthos.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.id.slice(0, 8)}… · {formatBytes(asset.size_bytes)} · {asset.crs ?? "CRS por validar"}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">Densidad objetivo (plantas/ha)</span>
            <input className="mt-2 w-full" type="number" min="1" step="1" value={targetDensity} onChange={(event) => setTargetDensity(event.target.value)} />
          </label>
          <label className="text-sm">
            <span className="font-medium">Excel de coordenadas</span>
            <input className="mt-2 block w-full" type="file" accept=".xls,.xlsx" onChange={(event) => setBoundaryExcel(event.target.files?.[0] ?? null)} />
          </label>
          <label className="text-sm">
            <span className="font-medium">Hoja del Excel</span>
            <input className="mt-2 w-full" value={boundarySheet} onChange={(event) => setBoundarySheet(event.target.value)} placeholder="Hoja1" />
          </label>
          <label className="text-sm md:col-span-2">
            <span className="font-medium">GeoPackage de polígonos a excluir (opcional)</span>
            <input className="mt-2 block w-full" type="file" accept=".gpkg" onChange={(event) => setExclusionsGpkg(event.target.files?.[0] ?? null)} />
            <span className="muted mt-1 block text-xs">Si contiene varias capas espaciales, se combinan para la exclusión.</span>
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="metric-card"><p className="muted text-sm">Excel</p><p className="mt-2 font-semibold">{boundaryExcel?.name ?? "Pendiente"}</p></div>
          <div className="metric-card"><p className="muted text-sm">Exclusiones</p><p className="mt-2 font-semibold">{exclusionsGpkg?.name ?? "No aplican"}</p></div>
          <div className="metric-card"><p className="muted text-sm">Ortofoto</p><p className="mt-2 font-semibold">{selectedOrtho ? formatBytes(selectedOrtho.size_bytes) : "Pendiente"}</p></div>
        </div>
        <button
          className="btn-primary"
          disabled={busy !== null || job?.status === "running" || !runtime?.ready || !farmId || !plotId || !orthophotoAssetId || !boundaryExcel || !boundarySheet.trim() || !(Number(targetDensity) > 0)}
          onClick={() => void execute()}
        >
          {busy === "run" ? "Preparando análisis…" : "Ejecutar análisis completo"}
        </button>
      </section>

      {job && (
        <section className="surface space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="eyebrow">Ejecución</div>
              <h2 className="text-lg font-semibold">Progreso del pipeline</h2>
              <p className="muted mt-1 text-sm">{job.progress_percent}% · estado: {job.status} · trabajo {job.job_id.slice(0, 8)}…</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {job.status === "running" && <button className="btn-secondary" disabled={busy !== null} onClick={() => void action("stop")}>{busy === "stop" ? "Deteniendo…" : "Detener"}</button>}
              {["failed", "stopped", "paused"].includes(job.status) && <button className="btn-secondary" disabled={busy !== null} onClick={() => void action("resume")}>{busy === "resume" ? "Reanudando…" : "Reanudar ejecución"}</button>}
              {job.report_ready && <button className="btn-primary" disabled={busy !== null} onClick={() => void downloadReport()}>{busy === "report" ? "Preparando PDF…" : "Descargar informe PDF"}</button>}
            </div>
          </div>
          {job.campaign_id ? (
            <div className="status-banner status-banner-info text-sm">
              <strong>Campaign DBI:</strong> {job.campaign_id} · vínculo técnico activo para este análisis de densidad.
            </div>
          ) : (
            <div className="status-banner status-banner-warning text-sm">
              <strong>Campaign DBI:</strong> No disponible. Este es un trabajo histórico creado antes de la incorporación de Campaign.
            </div>
          )}
          <div>
            <div className="mb-1 flex justify-between text-xs"><span>17 etapas</span><span>{job.progress_percent}%</span></div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10"><div className="h-full bg-slate-700 dark:bg-white" style={{ width: `${job.progress_percent}%` }} /></div>
          </div>
          {job.error && <div className="status-banner status-banner-danger">{job.error}</div>}
          <div className="grid gap-3 md:grid-cols-2">
            {job.stages.map((stage, index) => (
              <div key={stage.key} className={stageClass(stage.status)}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{index + 1}. {stage.title}</span>
                  <span className="text-xs font-semibold">{stageLabel(stage.status)}</span>
                </div>
                {stage.error && <p className="mt-2 text-xs">{stage.error}</p>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
