import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/app/api";

type PilotContext = {
  company_id: number;
  tenant_ref: string;
  organization_ref: string;
  principal_ref: string;
  farms_authorized: number;
  plots_authorized: number;
};

type RuntimeState = {
  local_mode: boolean;
  storage_ready: boolean;
  public_url: string | null;
};

type Company = {
  id: number;
  nombre?: string;
  name?: string;
  ruc: string;
};

type Farm = {
  id: string;
  organization_ref: string;
  code: string;
  name: string;
  status: string;
};

type Plot = {
  id: string;
  farm_id: string;
  code: string;
  name: string;
  area_hectares: string | number | null;
  status: string;
};

type Asset = {
  id: string;
  farm_id: string;
  plot_id: string | null;
  asset_kind: string;
  status: string;
  content_type: string;
  size_bytes: number;
  crs: string | null;
  verified_at: string | null;
};

type MultiPolygon = {
  type: "MultiPolygon";
  coordinates: number[][][][];
};

type BoundaryStats = {
  polygons: number;
  points: number;
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
};

function tenantHeaders(context: PilotContext) {
  return { "X-DBI-Tenant": context.tenant_ref };
}

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return String(detail.message);
  return fallback;
}

function normalizeBoundary(input: any): MultiPolygon {
  const geometries: any[] = [];

  if (input?.type === "FeatureCollection") {
    for (const feature of input.features ?? []) {
      if (feature?.geometry) geometries.push(feature.geometry);
    }
  } else if (input?.type === "Feature") {
    if (input.geometry) geometries.push(input.geometry);
  } else if (input?.type) {
    geometries.push(input);
  }

  const polygons: number[][][][] = [];
  for (const geometry of geometries) {
    if (geometry?.type === "Polygon" && Array.isArray(geometry.coordinates)) {
      polygons.push(geometry.coordinates);
    } else if (
      geometry?.type === "MultiPolygon" &&
      Array.isArray(geometry.coordinates)
    ) {
      polygons.push(...geometry.coordinates);
    }
  }

  if (!polygons.length) {
    throw new Error(
      "El GeoJSON debe contener al menos un Polygon o MultiPolygon.",
    );
  }

  return { type: "MultiPolygon", coordinates: polygons };
}

function boundaryStats(boundary: MultiPolygon): BoundaryStats {
  let points = 0;
  let minLon = Number.POSITIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;

  for (const polygon of boundary.coordinates) {
    for (const ring of polygon) {
      for (const position of ring) {
        if (!Array.isArray(position) || position.length < 2) {
          throw new Error("El GeoJSON contiene una posición inválida.");
        }
        const lon = Number(position[0]);
        const lat = Number(position[1]);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
          throw new Error("El GeoJSON contiene coordenadas no numéricas.");
        }
        points += 1;
        minLon = Math.min(minLon, lon);
        minLat = Math.min(minLat, lat);
        maxLon = Math.max(maxLon, lon);
        maxLat = Math.max(maxLat, lat);
      }
    }
  }

  return {
    polygons: boundary.coordinates.length,
    points,
    minLon,
    minLat,
    maxLon,
    maxLat,
  };
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 2)} ${units[index]}`;
}

export default function DbiPilotPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);

  const [company, setCompany] = useState<Company | null>(null);
  const [context, setContext] = useState<PilotContext | null>(null);
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [farms, setFarms] = useState<Farm[]>([]);
  const [plotsByFarm, setPlotsByFarm] = useState<Record<string, Plot[]>>({});
  const [assetsByFarm, setAssetsByFarm] = useState<Record<string, Asset[]>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [farmCode, setFarmCode] = useState("FINCA-001");
  const [farmName, setFarmName] = useState("");

  const [plotFarmId, setPlotFarmId] = useState("");
  const [plotCode, setPlotCode] = useState("LOTE-001");
  const [plotName, setPlotName] = useState("");
  const [plotArea, setPlotArea] = useState("");
  const [geoJsonText, setGeoJsonText] = useState("");
  const [geoJsonName, setGeoJsonName] = useState("");

  const [orthoFarmId, setOrthoFarmId] = useState("");
  const [orthoPlotId, setOrthoPlotId] = useState("");
  const [orthoCrs, setOrthoCrs] = useState("");
  const [orthoFile, setOrthoFile] = useState<File | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);

  const parsedBoundary = useMemo(() => {
    if (!geoJsonText.trim()) return null;
    try {
      const boundary = normalizeBoundary(JSON.parse(geoJsonText));
      return { boundary, stats: boundaryStats(boundary), error: null as string | null };
    } catch (parseError) {
      return {
        boundary: null,
        stats: null,
        error:
          parseError instanceof Error
            ? parseError.message
            : "No se pudo interpretar el GeoJSON.",
      };
    }
  }, [geoJsonText]);

  const loadData = useCallback(async (ctx: PilotContext) => {
    const config = { headers: tenantHeaders(ctx) };
    const { data: farmRows } = await api.get<Farm[]>(
      `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms`,
      config,
    );
    const nextFarms = Array.isArray(farmRows) ? farmRows : [];
    setFarms(nextFarms);

    const plotEntries = await Promise.all(
      nextFarms.map(async (farm) => {
        const { data } = await api.get<Plot[]>(
          `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms/${farm.id}/plots`,
          config,
        );
        return [farm.id, Array.isArray(data) ? data : []] as const;
      }),
    );
    const assetEntries = await Promise.all(
      nextFarms.map(async (farm) => {
        const { data } = await api.get<Asset[]>(
          `/api/v1/dbi/organizations/${encodeURIComponent(ctx.organization_ref)}/farms/${farm.id}/assets`,
          config,
        );
        return [farm.id, Array.isArray(data) ? data : []] as const;
      }),
    );

    const nextPlots = Object.fromEntries(plotEntries);
    setPlotsByFarm(nextPlots);
    setAssetsByFarm(Object.fromEntries(assetEntries));

    const firstFarm = nextFarms[0]?.id ?? "";
    setPlotFarmId((current) =>
      current && nextFarms.some((farm) => farm.id === current) ? current : firstFarm,
    );
    setOrthoFarmId((current) =>
      current && nextFarms.some((farm) => farm.id === current) ? current : firstFarm,
    );
  }, []);

  const bootstrap = useCallback(
    async (showMessage = false) => {
      if (!Number.isInteger(companyId) || companyId <= 0) {
        throw new Error("Identificador de empresa inválido.");
      }
      const { data: ctx } = await api.post<PilotContext>(
        `/api/v1/dbi/pilot/companies/${companyId}/bootstrap`,
      );
      setContext(ctx);
      await loadData(ctx);
      if (showMessage) {
        setMessage("Autoridad DBI local reconciliada correctamente.");
      }
      return ctx;
    },
    [companyId, loadData],
  );

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const [{ data: companyData }, { data: runtimeData }] = await Promise.all([
          api.get<Company>(`/api/v1/companies/${companyId}`),
          api.get<RuntimeState>("/api/v1/dbi/pilot/runtime"),
        ]);
        if (!active) return;
        setCompany(companyData);
        setRuntime(runtimeData);
        await bootstrap(false);
      } catch (initialError) {
        if (!active) return;
        setError(
          errorText(
            initialError,
            "No se pudo preparar el módulo agrícola DBI para esta empresa.",
          ),
        );
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [bootstrap, companyId]);

  useEffect(() => {
    const plots = plotsByFarm[orthoFarmId] ?? [];
    setOrthoPlotId((current) =>
      current && plots.some((plot) => plot.id === current)
        ? current
        : plots[0]?.id ?? "",
    );
  }, [orthoFarmId, plotsByFarm]);

  const createFarm = async () => {
    if (!context || !farmCode.trim() || !farmName.trim()) return;
    setBusy("farm");
    setError(null);
    setMessage(null);
    try {
      await api.post(
        `/api/v1/dbi/organizations/${encodeURIComponent(context.organization_ref)}/farms`,
        {
          code: farmCode.trim(),
          name: farmName.trim(),
          status: "active",
        },
        { headers: tenantHeaders(context) },
      );
      await bootstrap(false);
      setFarmName("");
      setMessage("Finca creada y autorizada para esta empresa.");
    } catch (createError) {
      setError(errorText(createError, "No se pudo crear la finca."));
    } finally {
      setBusy(null);
    }
  };

  const loadGeoJsonFile = async (file: File | null) => {
    if (!file) return;
    try {
      const text = await file.text();
      normalizeBoundary(JSON.parse(text));
      setGeoJsonText(text);
      setGeoJsonName(file.name);
      setError(null);
    } catch (readError) {
      setError(
        readError instanceof Error
          ? readError.message
          : "No se pudo leer el archivo GeoJSON.",
      );
    }
  };

  const createPlot = async () => {
    if (!context || !plotFarmId) return;
    if (!parsedBoundary?.boundary) {
      setError(parsedBoundary?.error ?? "Debes cargar un límite GeoJSON válido.");
      return;
    }
    if (!plotCode.trim() || !plotName.trim()) {
      setError("Código y nombre del lote son obligatorios.");
      return;
    }

    const areaValue = plotArea.trim() ? Number(plotArea) : null;
    if (areaValue !== null && (!Number.isFinite(areaValue) || areaValue <= 0)) {
      setError("El área debe ser un número positivo en hectáreas.");
      return;
    }

    setBusy("plot");
    setError(null);
    setMessage(null);
    try {
      await api.post(
        `/api/v1/dbi/organizations/${encodeURIComponent(context.organization_ref)}/farms/${plotFarmId}/plots`,
        {
          code: plotCode.trim(),
          name: plotName.trim(),
          area_hectares: areaValue,
          boundary: parsedBoundary.boundary,
          status: "active",
        },
        { headers: tenantHeaders(context) },
      );
      await bootstrap(false);
      setPlotName("");
      setGeoJsonText("");
      setGeoJsonName("");
      setMessage("Lote creado con límite espacial EPSG:4326 validado por DBI.");
    } catch (createError) {
      setError(errorText(createError, "No se pudo crear el lote."));
    } finally {
      setBusy(null);
    }
  };

  const uploadOrthophoto = async () => {
    if (!context || !orthoFarmId || !orthoPlotId || !orthoFile || !orthoCrs.trim()) {
      setError("Selecciona finca, lote, CRS y archivo GeoTIFF.");
      return;
    }

    setBusy("ortho");
    setError(null);
    setMessage(null);
    setUploadPct(0);

    const body = new FormData();
    body.append("farm_id", orthoFarmId);
    body.append("plot_id", orthoPlotId);
    body.append("crs", orthoCrs.trim());
    body.append("file", orthoFile);

    try {
      const { data } = await api.post(
        `/api/v1/dbi/pilot/companies/${companyId}/orthophoto`,
        body,
        {
          onUploadProgress: (event) => {
            if (event.total) {
              setUploadPct(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            }
          },
        },
      );
      await loadData(context);
      setOrthoFile(null);
      setUploadPct(100);
      setMessage(
        `Ortofoto verificada: ${String(data.asset_id).slice(0, 8)}… · ${formatBytes(
          Number(data.size_bytes),
        )}.`,
      );
    } catch (uploadError) {
      setError(errorText(uploadError, "No se pudo cargar la ortofoto."));
    } finally {
      setBusy(null);
    }
  };

  const baseForField = useMemo(() => {
    const publicUrl = runtime?.public_url?.replace(/\/+$/, "");
    return publicUrl || window.location.origin.replace(/\/+$/, "");
  }, [runtime?.public_url]);

  const inspectionUrl = (farm: Farm, plot: Plot) => {
    if (!context) return "#";
    return `${baseForField}/dbi/organizations/${encodeURIComponent(
      context.organization_ref,
    )}/farms/${farm.id}/plots/${plot.id}/inspection/new?tenant=${encodeURIComponent(
      context.tenant_ref,
    )}`;
  };

  const copyInspectionUrl = async (farm: Farm, plot: Plot) => {
    const url = inspectionUrl(farm, plot);
    try {
      await navigator.clipboard.writeText(url);
      setMessage("Enlace INSPECT copiado. Ábrelo en Safari del iPad.");
    } catch {
      setError(`No se pudo copiar automáticamente. Enlace: ${url}`);
    }
  };

  if (loading) {
    return <div className="card">Preparando módulo agrícola DBI…</div>;
  }

  if (!context || (error && !company)) {
    return (
      <div className="space-y-4">
        <div className="status-banner status-banner-danger">{error ?? "DBI no disponible."}</div>
        <Link to={`/companies/${companyId}`} className="btn-ghost">
          ← Volver a empresa
        </Link>
      </div>
    );
  }

  const companyName = company?.nombre ?? company?.name ?? `Empresa ${companyId}`;

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">Primera prueba real</span>
          <h1>Agricultura DBI · {companyName}</h1>
          <p className="page-subtitle">
            Empresa → finca → lote georreferenciado → ortofoto → captura INSPECT en iPad.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-secondary"
            disabled={busy !== null}
            onClick={() => void bootstrap(true)}
          >
            Reconciliar DBI
          </button>
          <Link to={`/companies/${companyId}`} className="btn-ghost">
            ← Empresa
          </Link>
        </div>
      </div>

      {error && <div className="status-banner status-banner-danger">{error}</div>}
      {message && <div className="status-banner status-banner-success">{message}</div>}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="metric-card">
          <p className="muted text-sm">Tenant local</p>
          <p className="mt-2 font-semibold">{context.tenant_ref}</p>
        </div>
        <div className="metric-card">
          <p className="muted text-sm">Organización DBI</p>
          <p className="mt-2 break-all font-semibold">{context.organization_ref}</p>
        </div>
        <div className="metric-card">
          <p className="muted text-sm">Fincas</p>
          <p className="mt-2 text-xl font-semibold">{farms.length}</p>
        </div>
        <div className="metric-card">
          <p className="muted text-sm">Almacenamiento</p>
          <p className="mt-2 font-semibold">
            {runtime?.storage_ready ? "Listo" : "No disponible"}
          </p>
        </div>
      </div>

      {!runtime?.public_url && (
        <div className="status-banner status-banner-warning text-sm">
          El Control Center todavía no reporta URL pública. Puedes preparar finca, lote y
          ortofoto desde la laptop; para el iPad inicia el túnel y pulsa “Reconciliar DBI”
          o recarga esta pantalla.
        </div>
      )}

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 1</div>
          <h2 className="text-lg font-semibold">Crear finca</h2>
          <p className="muted mt-1 text-sm">
            La finca quedará vinculada a esta empresa mediante su organización DBI local.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-[220px_1fr_auto]">
          <input
            value={farmCode}
            onChange={(event) => setFarmCode(event.target.value)}
            placeholder="FINCA-001"
          />
          <input
            value={farmName}
            onChange={(event) => setFarmName(event.target.value)}
            placeholder="Nombre de la finca"
          />
          <button
            className="btn-primary"
            disabled={busy !== null || !farmCode.trim() || !farmName.trim()}
            onClick={() => void createFarm()}
          >
            {busy === "farm" ? "Creando…" : "Crear finca"}
          </button>
        </div>
      </section>

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 2</div>
          <h2 className="text-lg font-semibold">Crear lote e importar coordenadas</h2>
          <p className="muted mt-1 text-sm">
            Importa GeoJSON en EPSG:4326. DBI normaliza Polygon/MultiPolygon y valida
            topología, longitud y latitud.
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            <span className="font-medium">Finca</span>
            <select
              className="mt-2 w-full"
              value={plotFarmId}
              onChange={(event) => setPlotFarmId(event.target.value)}
            >
              <option value="">Seleccionar finca</option>
              {farms.map((farm) => (
                <option key={farm.id} value={farm.id}>
                  {farm.code} · {farm.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">Área ha</span>
            <input
              className="mt-2 w-full"
              type="number"
              min="0"
              step="0.0001"
              value={plotArea}
              onChange={(event) => setPlotArea(event.target.value)}
              placeholder="Ej. 8.4250"
            />
          </label>
          <label className="text-sm">
            <span className="font-medium">Código lote</span>
            <input
              className="mt-2 w-full"
              value={plotCode}
              onChange={(event) => setPlotCode(event.target.value)}
              placeholder="LOTE-001"
            />
          </label>
          <label className="text-sm">
            <span className="font-medium">Nombre lote</span>
            <input
              className="mt-2 w-full"
              value={plotName}
              onChange={(event) => setPlotName(event.target.value)}
              placeholder="Lote 01"
            />
          </label>
        </div>

        <label className="block text-sm">
          <span className="font-medium">Archivo GeoJSON</span>
          <input
            className="mt-2 block w-full"
            type="file"
            accept=".geojson,.json,application/geo+json,application/json"
            onChange={(event) => void loadGeoJsonFile(event.target.files?.[0] ?? null)}
          />
        </label>

        {geoJsonName && <div className="chip">Archivo: {geoJsonName}</div>}
        {parsedBoundary?.error && (
          <div className="status-banner status-banner-danger text-sm">
            {parsedBoundary.error}
          </div>
        )}
        {parsedBoundary?.stats && (
          <div className="grid gap-3 md:grid-cols-3">
            <div className="metric-card">
              <p className="muted text-sm">Polígonos</p>
              <p className="mt-2 font-semibold">{parsedBoundary.stats.polygons}</p>
            </div>
            <div className="metric-card">
              <p className="muted text-sm">Vértices</p>
              <p className="mt-2 font-semibold">{parsedBoundary.stats.points}</p>
            </div>
            <div className="metric-card">
              <p className="muted text-sm">BBOX lon/lat</p>
              <p className="mt-2 text-xs font-medium">
                {parsedBoundary.stats.minLon.toFixed(6)}, {parsedBoundary.stats.minLat.toFixed(6)}
                {" → "}
                {parsedBoundary.stats.maxLon.toFixed(6)}, {parsedBoundary.stats.maxLat.toFixed(6)}
              </p>
            </div>
          </div>
        )}

        <button
          className="btn-primary"
          disabled={busy !== null || !plotFarmId || !parsedBoundary?.boundary}
          onClick={() => void createPlot()}
        >
          {busy === "plot" ? "Creando lote…" : "Crear lote georreferenciado"}
        </button>
      </section>

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 3</div>
          <h2 className="text-lg font-semibold">Cargar ortofoto GeoTIFF</h2>
          <p className="muted mt-1 text-sm">
            Haz esta carga desde la laptop. El backend calcula SHA-256, guarda el archivo
            privado en disco y verifica su integridad antes de marcarlo como “verified”.
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            <span className="font-medium">Finca</span>
            <select
              className="mt-2 w-full"
              value={orthoFarmId}
              onChange={(event) => setOrthoFarmId(event.target.value)}
            >
              <option value="">Seleccionar finca</option>
              {farms.map((farm) => (
                <option key={farm.id} value={farm.id}>
                  {farm.code} · {farm.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">Lote</span>
            <select
              className="mt-2 w-full"
              value={orthoPlotId}
              onChange={(event) => setOrthoPlotId(event.target.value)}
            >
              <option value="">Seleccionar lote</option>
              {(plotsByFarm[orthoFarmId] ?? []).map((plot) => (
                <option key={plot.id} value={plot.id}>
                  {plot.code} · {plot.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="font-medium">CRS real de la ortofoto</span>
            <input
              className="mt-2 w-full"
              value={orthoCrs}
              onChange={(event) => setOrthoCrs(event.target.value)}
              placeholder="Ej. EPSG:32717"
            />
          </label>
          <label className="text-sm">
            <span className="font-medium">GeoTIFF</span>
            <input
              className="mt-2 block w-full"
              type="file"
              accept=".tif,.tiff,image/tiff"
              onChange={(event) => setOrthoFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        {orthoFile && (
          <div className="chip">
            {orthoFile.name} · {formatBytes(orthoFile.size)}
          </div>
        )}

        {uploadPct !== null && (
          <div>
            <div className="mb-1 flex justify-between text-xs">
              <span>Carga</span>
              <span>{uploadPct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
              <div className="h-full bg-slate-700 dark:bg-white" style={{ width: `${uploadPct}%` }} />
            </div>
          </div>
        )}

        <button
          className="btn-primary"
          disabled={
            busy !== null ||
            !orthoFarmId ||
            !orthoPlotId ||
            !orthoCrs.trim() ||
            !orthoFile
          }
          onClick={() => void uploadOrthophoto()}
        >
          {busy === "ortho" ? "Cargando y verificando…" : "Cargar ortofoto"}
        </button>
      </section>

      <section className="surface space-y-4">
        <div>
          <div className="eyebrow">Paso 4</div>
          <h2 className="text-lg font-semibold">Abrir INSPECT en iPad</h2>
          <p className="muted mt-1 text-sm">
            Cada lote ofrece un enlace con tenant, organización, finca y lote ya
            identificados. Inicia sesión desde Safari y permite la ubicación.
          </p>
        </div>

        {farms.length === 0 && <p className="muted">Primero crea una finca.</p>}

        <div className="space-y-4">
          {farms.map((farm) => {
            const plots = plotsByFarm[farm.id] ?? [];
            const assets = assetsByFarm[farm.id] ?? [];
            return (
              <div key={farm.id} className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold">{farm.code} · {farm.name}</div>
                    <div className="muted mt-1 text-xs">{farm.id}</div>
                  </div>
                  <span className="chip">{plots.length} lote(s)</span>
                </div>

                <div className="mt-4 space-y-3">
                  {plots.map((plot) => {
                    const orthos = assets.filter(
                      (asset) =>
                        asset.plot_id === plot.id && asset.asset_kind === "orthophoto",
                    );
                    const latest = orthos[orthos.length - 1];
                    return (
                      <div key={plot.id} className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <div className="font-medium">{plot.code} · {plot.name}</div>
                            <div className="muted mt-1 text-xs">
                              {plot.area_hectares ? `${plot.area_hectares} ha · ` : ""}
                              {plot.id}
                            </div>
                            <div className="mt-2 text-xs">
                              Ortofoto:{" "}
                              {latest
                                ? `${latest.status} · ${formatBytes(latest.size_bytes)} · ${
                                    latest.crs ?? "sin CRS"
                                  }`
                                : "no cargada"}
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              className="btn-secondary"
                              type="button"
                              onClick={() => void copyInspectionUrl(farm, plot)}
                            >
                              Copiar enlace iPad
                            </button>
                            <a
                              className="btn-primary"
                              href={inspectionUrl(farm, plot)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Abrir INSPECT
                            </a>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  {plots.length === 0 && <p className="muted text-sm">Sin lotes todavía.</p>}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
