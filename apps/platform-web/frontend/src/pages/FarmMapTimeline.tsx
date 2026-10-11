import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
  type MapMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { GoogleSatelliteViewer } from "@/components/GoogleSatelliteViewer";
import { api } from "@/app/api";
import {
  getVectorLayer, listVectorLayers, listVectorCampaigns, listGISImports, getGISImportPreview, publishReviewedGISImport, publishGeoJSON, stageGISOriginal, vectorExtent,
  type VectorLayerInfo, type VectorLayerKind, type VectorLayerDetail, type VectorCampaign, type GISImportReceipt,
} from "@/features/portalVectors";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import {
  apiResourceUrl,
  getFarmMapTimeline,
  getPlotMapTimeline,
  mapLibreDbiHeaders,
  type FarmMapTimelineResponse,
  type MapLayerType,
  type PlotMapTimelineResponse,
  type RasterTileTimelineEntry,
} from "@/features/mapTimeline";
import { createGISFeatureDetails, GIS_KIND_COLORS, GIS_KIND_LABELS } from "@/features/gisPresentation";

setWorkerUrl(mapWorkerUrl);

const EMPTY_MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "dbi-neutral-background",
      type: "background",
      paint: {
        "background-color": "#dfe8e5",
      },
    },
  ],
};

type TimelineData = FarmMapTimelineResponse | PlotMapTimelineResponse;

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("es-EC");
}

function sameCapture(a: string, b: string): boolean {
  const first = Date.parse(a), second = Date.parse(b);
  return Number.isFinite(first) && Number.isFinite(second)
    ? first === second : a === b;
}

function isPlotTimeline(data: TimelineData | null): data is PlotMapTimelineResponse {
  return data?.schema_version === "plot-map-timeline.v1";
}

function isRasterEntry(
  entry: TimelineData["timeline"][number],
): entry is RasterTileTimelineEntry {
  return "tile_url_template" in entry && entry.layer_type === "rgb";
}

export default function FarmMapTimeline() {
  const {
    fincaId,
    organizationRef,
    farmId,
    plotId,
  } = useParams<{
    fincaId?: string;
    organizationRef?: string;
    farmId?: string;
    plotId?: string;
  }>();
  const [searchParams] = useSearchParams();
  const tenantRef = searchParams.get("tenant")?.trim() ?? "";

  const effectiveFarmId = farmId ?? fincaId ?? "";

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const activeRasterIdsRef = useRef<string[]>([]);
  const activeVectorIdsRef = useRef<string[]>([]);
  const fittedRef = useRef<string | null>(null);

  const [mapReady, setMapReady] = useState(false);
  const [data, setData] = useState<TimelineData | null>(null);
  const [selectedLayers, setSelectedLayers] = useState<Set<MapLayerType>>(
    new Set(),
  );
  const [selectedDate, setSelectedDate] = useState("");
  const [comparisonDate, setComparisonDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [farmLabel, setFarmLabel] = useState("Finca");
  const [plotLabel, setPlotLabel] = useState("Lote");
  const [vectorLayers, setVectorLayers] = useState<VectorLayerInfo[]>([]);
  // La vista descarta recibos de otro tenant/lote incluso durante navegación.
  const [gisImportCache, setGISImportCache] = useState<{
    scopeKey: string;
    items: GISImportReceipt[];
  } | null>(null);
  const [gisRefreshBusy, setGISRefreshBusy] = useState(false);
  const [reviewedImportId, setReviewedImportId] = useState<string | null>(null);
  const [gisPreviewVector, setGISPreviewVector] = useState<VectorLayerDetail | null>(null);
  const [gisReviewBusy, setGISReviewBusy] = useState(false);
  const [vectorCampaigns, setVectorCampaigns] = useState<VectorCampaign[]>([]);
  const [campaignLoadError, setCampaignLoadError] = useState(false);
  const [chosenUploadCampaign, setChosenUploadCampaign] = useState("");
  const [vectorDetails, setVectorDetails] = useState<Record<string, VectorLayerDetail>>({});
  const [selectedVectorIds, setSelectedVectorIds] = useState<Set<string>>(new Set());
  const [canPublish, setCanPublish] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadKind, setUploadKind] = useState<VectorLayerKind>("density_hexagons");
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);

  const realLocator = useMemo(() => {
    if (!organizationRef || !farmId || !plotId || !tenantRef) return null;
    return {
      tenantRef,
      organizationRef,
      farmId,
      plotId,
    };
  }, [farmId, organizationRef, plotId, tenantRef]);

  const gisScopeKey = realLocator
    ? [realLocator.tenantRef, realLocator.organizationRef, realLocator.farmId, realLocator.plotId].join("|")
    : "";
  const gisImports = gisImportCache?.scopeKey === gisScopeKey ? gisImportCache.items : [];
  const hasPendingGISImports = gisImports.some(item =>
    item.status === "received" || item.status === "processing"
  );
  const useGoogleBase = Boolean(import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim()) && Boolean(realLocator);

  useEffect(() => {
    let active = true;
    if (!realLocator) return;
    const base = `/api/v1/dbi/organizations/${encodeURIComponent(realLocator.organizationRef)}/farms/${encodeURIComponent(realLocator.farmId)}`;
    const config = { headers: { "X-DBI-Tenant": realLocator.tenantRef } };
    Promise.all([
      api.get<{ name: string }>(base, config),
      api.get<{ name: string }>(`${base}/plots/${encodeURIComponent(realLocator.plotId)}`, config),
    ]).then(([farm, plot]) => {
      if (!active) return;
      setFarmLabel(farm.data.name);
      setPlotLabel(plot.data.name);
    }).catch(() => {
      if (!active) return;
      setFarmLabel("Finca");
      setPlotLabel("Lote");
    });
    return () => { active = false; };
  }, [realLocator]);


  useEffect(() => {
    let active = true;
    if (!realLocator) return;
    setVectorCampaigns([]);
    setGISPreviewVector(null);
    setReviewedImportId(null);
    setCampaignLoadError(false);
    setChosenUploadCampaign("");
    listVectorCampaigns(realLocator).then(campaigns => {
      if (active) setVectorCampaigns(campaigns);
    }).catch(() => {
      if (active) setCampaignLoadError(true);
    });
    listGISImports(realLocator).then(receipts => {
      if (active) setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
    }).catch(() => {
      if (active) setGISImportCache({ scopeKey: gisScopeKey, items: [] });
    });
    listVectorLayers(realLocator).then(layers => {
      if (!active) return;
      setVectorLayers(layers);
      setSelectedVectorIds(new Set(layers.map(item => item.id)));
    }).catch(() => { if (active) setVectorLayers([]); });

    api.get<Array<{
      tenant_ref: string;
      farms: Array<{ id: string; organization_ref: string; can_publish_layers: boolean; plots: Array<{ id: string }> }>;
    }>>("/api/v1/dbi/portal/accounts")
      .then(({ data: accounts }) => {
        if (!active) return;
        setCanPublish(accounts.some(account =>
          account.tenant_ref === realLocator.tenantRef &&
          account.farms.some(farm =>
            farm.id === realLocator.farmId &&
            farm.organization_ref === realLocator.organizationRef &&
            farm.can_publish_layers &&
            farm.plots.some(plot => plot.id === realLocator.plotId)
          )
        ));
      }).catch(() => { if (active) setCanPublish(false); });
    return () => { active = false; };
  }, [realLocator]);


  useEffect(() => {
    if (useGoogleBase || !mapContainerRef.current || mapRef.current) return;

    const map = new MapLibreMap({
      container: mapContainerRef.current,
      style: EMPTY_MAP_STYLE,
      center: [-79.8, -3.3],
      zoom: 7,
      attributionControl: false,
      transformRequest: (url) => {
        if (!tenantRef || !url.includes("/api/v1/dbi/")) return { url };
        return {
          url,
          headers: mapLibreDbiHeaders(tenantRef),
        };
      },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => setMapReady(true));
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      activeRasterIdsRef.current = [];
      activeVectorIdsRef.current = [];
      fittedRef.current = null;
      setMapReady(false);
    };
  }, [tenantRef, useGoogleBase]);

  useEffect(() => {
    let active = true;

    if (!effectiveFarmId) {
      setError("No se recibió un identificador de finca válido.");
      setLoading(false);
      return () => {
        active = false;
      };
    }

    if ((organizationRef || plotId) && !realLocator) {
      setError(
        "La ruta Raster requiere organización, finca, lote y ?tenant=<tenant_ref>.",
      );
      setLoading(false);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    setError(null);

    const request = realLocator
      ? getPlotMapTimeline(realLocator)
      : getFarmMapTimeline(effectiveFarmId);

    request
      .then((response) => {
        if (!active) return;
        setData(response);

        const realLayerTypes = new Set<MapLayerType>(
          response.timeline.map((entry) => entry.layer_type),
        );
        setSelectedLayers(realLayerTypes);

        const dates = Array.from(
          new Set(response.timeline.map((entry) => entry.captured_at)),
        ).sort();
        setSelectedDate(dates.at(-1) ?? "");
        setComparisonDate("");
      })
      .catch((requestError) => {
        if (!active) return;
        setError(
          requestError?.response?.data?.detail ??
            requestError?.message ??
            "No se pudo cargar la cronología cartográfica.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [
    effectiveFarmId,
    organizationRef,
    plotId,
    realLocator,
  ]);

  const dates = useMemo(() =>
    Array.from(new Set([
      ...(data?.timeline ?? []).map(entry => entry.captured_at),
      ...vectorCampaigns.map(campaign => campaign.captured_at),
    ])).sort(),
    [data?.timeline, vectorCampaigns],
  );

  const availableLayerTypes = useMemo(
    () => new Set((data?.timeline ?? []).map((entry) => entry.layer_type)),
    [data?.timeline],
  );

  const visibleEntries = useMemo(
    () =>
      (data?.timeline ?? []).filter(
        (entry) =>
          selectedLayers.has(entry.layer_type) &&
          (selectedDate === "" || sameCapture(entry.captured_at, selectedDate)),
      ),
    [data?.timeline, selectedDate, selectedLayers],
  );


  const activeCampaignIds = useMemo(() => new Set(
    vectorCampaigns
      .filter(campaign => !selectedDate || sameCapture(campaign.captured_at, selectedDate))
      .map(campaign => campaign.id)
  ), [vectorCampaigns, selectedDate]);

  const visibleVectorMeta = useMemo(() =>
    vectorLayers.filter(layer => activeCampaignIds.has(layer.campaign_id)),
    [vectorLayers, activeCampaignIds],
  );

  useEffect(() => {
    let active = true;
    if (!realLocator) return;
    const toLoad = visibleVectorMeta.filter(item =>
      selectedVectorIds.has(item.id) && !vectorDetails[item.id]
    );
    if (toLoad.length) {
      Promise.all(toLoad.map(item => getVectorLayer(realLocator, item.id)))
        .then(details => {
          if (!active) return;
          setVectorDetails(current => ({
            ...current, ...Object.fromEntries(details.map(detail => [detail.layer.id, detail])),
          }));
        }).catch(() => {
          // La consulta sigue protegida por tenant y lote; una capa fallida no se dibuja.
        });
    }
    return () => { active = false; };
  }, [realLocator, visibleVectorMeta, selectedVectorIds, vectorDetails]);

  const visibleVectorDetails = useMemo(() => {
    const published = visibleVectorMeta.filter(meta => selectedVectorIds.has(meta.id))
      .map(meta => vectorDetails[meta.id])
      .filter((detail): detail is VectorLayerDetail => Boolean(detail));
    // Una vista previa solo se dibuja para el gestor, en la fecha técnica real.
    return gisPreviewVector && activeCampaignIds.has(gisPreviewVector.layer.campaign_id)
      ? [...published, gisPreviewVector] : published;
  }, [visibleVectorMeta, selectedVectorIds, vectorDetails, gisPreviewVector, activeCampaignIds]);

  const uploadCampaignChoices = useMemo(() =>
    vectorCampaigns.filter(campaign =>
      !selectedDate || sameCapture(campaign.captured_at, selectedDate)
    ),
    [vectorCampaigns, selectedDate],
  );
  const uploadCampaignId = uploadCampaignChoices.some(campaign => campaign.id === chosenUploadCampaign)
    ? chosenUploadCampaign : null;
  const gisBounds = useMemo(
    () => vectorExtent(visibleVectorDetails),
    [visibleVectorDetails],
  );
  const mapBounds = isPlotTimeline(data) && data.viewport_bounds
    ? data.viewport_bounds : gisBounds;

  // Reconsulta solo mientras el worker pueda cambiar el estado; sin polling para lectores.
  useEffect(() => {
    if (!realLocator || !canPublish || !hasPendingGISImports) return;
    let active = true;
    const interval = window.setInterval(() => {
      void listGISImports(realLocator).then(receipts => {
        if (active) setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
      }).catch(() => {
        // Conserva el último estado conocido; se volverá a intentar.
      });
    }, 15_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [realLocator, gisScopeKey, canPublish, hasPendingGISImports]);

  async function refreshGISImportStatus() {
    if (!realLocator || !canPublish) return;
    setGISRefreshBusy(true);
    try {
      const receipts = await listGISImports(realLocator);
      setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
    } catch {
      setUploadNotice("No se pudieron actualizar los archivos GIS. Intenta nuevamente.");
    } finally {
      setGISRefreshBusy(false);
    }
  }

  async function inspectGISImport(item: GISImportReceipt) {
    if (!realLocator || !canPublish) return;
    setGISReviewBusy(true);
    setUploadNotice(null);
    try {
      const campaign = vectorCampaigns.find(row => row.id === item.campaign_id);
      if (!campaign) throw new Error("No se encontró el levantamiento vinculado a este original.");
      const result = await getGISImportPreview(realLocator, item.id);
      setReviewedImportId(item.id);
      setSelectedDate(campaign.captured_at);
      setGISPreviewVector({
        layer: {
          id: `preview-${item.id}`,
          campaign_id: item.campaign_id, layer_kind: item.layer_kind,
          name: `VISTA PREVIA · ${item.name}`,
          feature_count: result.feature_count,
          created_at: item.created_at,
        },
        geojson: result.geojson,
      });
      setUploadNotice("Vista previa privada en el mapa. Revisa geometrías y atributos antes de aprobar.");
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } }, message?: string });
      setUploadNotice(typeof detail.response?.data?.detail === "string"
        ? detail.response.data.detail
        : detail.message || "No fue posible revisar la vista previa GIS.");
      setGISPreviewVector(null);
      setReviewedImportId(null);
    } finally {
      setGISReviewBusy(false);
    }
  }

  async function approveGISImport(item: GISImportReceipt) {
    if (!realLocator || !canPublish || reviewedImportId !== item.id
        || !gisPreviewVector || !activeCampaignIds.has(item.campaign_id)) return;
    setGISReviewBusy(true);
    try {
      const layer = await publishReviewedGISImport(realLocator, item.id);
      const [layers, receipts] = await Promise.all([
        listVectorLayers(realLocator), listGISImports(realLocator),
      ]);
      setVectorLayers(layers);
      setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
      setSelectedVectorIds(current => new Set([...current, layer.id]));
      setGISPreviewVector(null);
      setReviewedImportId(null);
      setUploadNotice("Capa GIS revisada y publicada para los usuarios autorizados del lote.");
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setUploadNotice(typeof detail === "string" ? detail : "No se pudo aprobar la capa GIS.");
    } finally {
      setGISReviewBusy(false);
    }
  }

  async function uploadSelectedGeoJSON() {
    if (!realLocator || !uploadCampaignId || !uploadFile) return;
    const isGeoJSON = /\.(geojson|json)$/i.test(uploadFile.name);
    const isGISOriginal = /\.(gpkg|zip)$/i.test(uploadFile.name);
    if (
      (!isGeoJSON && !isGISOriginal)
      || uploadFile.size < 1
      || uploadFile.size > (isGeoJSON ? 2 : 30) * 1024 * 1024
    ) {
      setUploadNotice("Selecciona GeoJSON de máximo 2 MiB o GPKG/SHP ZIP de máximo 30 MiB.");
      return;
    }
    setUploading(true);
    setUploadNotice(null);
    try {
      if (isGISOriginal) {
        await stageGISOriginal(
          realLocator, uploadFile, uploadCampaignId, uploadKind,
          uploadFile.name.replace(/\.(gpkg|zip)$/i, ""),
        );
        setGISImportCache({ scopeKey: gisScopeKey, items: await listGISImports(realLocator) });
        setUploadNotice(
          "Archivo original recibido en almacenamiento privado. Sigue pendiente la conversión y revisión; aún no está publicado.",
        );
      } else {
        const saved = await publishGeoJSON(
          realLocator, uploadFile, uploadCampaignId, uploadKind,
          uploadFile.name.replace(/\.(geojson|json)$/i, ""),
        );
        const layers = await listVectorLayers(realLocator);
        setVectorLayers(layers);
        setSelectedVectorIds(current => new Set([...current, saved.id]));
        setUploadNotice("Capa GeoJSON publicada para los usuarios autorizados de este lote.");
      }
      setUploadFile(null);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setUploadNotice(typeof detail === "string" ? detail : "No se pudo publicar la capa.");
    } finally {
      setUploading(false);
    }
  }

  const displayEntries = useMemo(() => {
    const selected = new Map<MapLayerType, RasterTileTimelineEntry>();
    const ordered = [...visibleEntries].sort((a, b) =>
      b.captured_at.localeCompare(a.captured_at),
    );
    for (const entry of ordered) {
      if (!isRasterEntry(entry) || selected.has(entry.layer_type)) continue;
      selected.set(entry.layer_type, entry);
    }
    return Array.from(selected.values());
  }, [visibleEntries]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    for (const id of activeRasterIdsRef.current) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
    activeRasterIdsRef.current = [];

    for (const entry of displayEntries) {
      const id = `dbi-raster-${entry.raster_product_id}`;
      map.addSource(id, {
        type: "raster",
        tiles: [apiResourceUrl(entry.tile_url_template)],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 22,
      });
      map.addLayer({
        id,
        type: "raster",
        source: id,
        paint: {
          "raster-opacity": 1,
        },
      });
      activeRasterIdsRef.current.push(id);
    }
    for (const vectorId of activeVectorIdsRef.current) {
      for (const suffix of ["-fill", "-line", "-point"]) {
        const id = `${vectorId}${suffix}`;
        if (map.getLayer(id)) map.moveLayer(id);
      }
    }
  }, [displayEntries, mapReady]);


  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    for (const id of activeVectorIdsRef.current) {
      for (const suffix of ["-point", "-line", "-fill"]) {
        if (map.getLayer(id + suffix)) map.removeLayer(id + suffix);
      }
      if (map.getSource(id)) map.removeSource(id);
    }
    activeVectorIdsRef.current = [];

    for (const vector of visibleVectorDetails) {
      const id = `dbi-vector-${vector.layer.id}`;
      map.addSource(id, {
        type: "geojson",
        data: vector.geojson as unknown as string,
      });
      map.addLayer({
        id: id + "-fill", type: "fill", source: id,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": GIS_KIND_COLORS[vector.layer.layer_kind],
          "fill-opacity": 0.25,
        },
      });
      map.addLayer({
        id: id + "-line", type: "line", source: id,
        paint: { "line-color": GIS_KIND_COLORS[vector.layer.layer_kind], "line-width": 2 },
      });
      map.addLayer({
        id: id + "-point", type: "circle", source: id,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 6,
          "circle-color": GIS_KIND_COLORS[vector.layer.layer_kind],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      });
      activeVectorIdsRef.current.push(id);
    }
  }, [mapReady, visibleVectorDetails]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    let currentPopup: Popup | null = null;
    const inspect = (event: MapMouseEvent) => {
      const layerIds = activeVectorIdsRef.current.flatMap(id =>
        ["-point", "-line", "-fill"].map(suffix => id + suffix)
      ).filter(id => Boolean(map.getLayer(id)));
      if (!layerIds.length) return;
      const feature = map.queryRenderedFeatures(event.point, { layers: layerIds })[0];
      if (!feature) return;
      const layerId = feature.source.replace(/^dbi-vector-/, "");
      const details = visibleVectorDetails.find(item => item.layer.id === layerId);
      if (!details) return;
      currentPopup?.remove();
      currentPopup = new Popup({ closeButton: true, maxWidth: "320px", offset: 12 })
        .setLngLat(event.lngLat)
        .setDOMContent(createGISFeatureDetails(
          document, details.layer.name,
          (feature.properties ?? {}) as Record<string, unknown>,
        ))
        .addTo(map);
    };
    map.on("click", inspect);
    return () => {
      map.off("click", inspect);
      currentPopup?.remove();
    };
  }, [mapReady, visibleVectorDetails]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !mapBounds) return;

    const fitKey = [
      realLocator?.plotId ?? effectiveFarmId,
      ...mapBounds.map((value) => value.toFixed(7)),
    ].join(":");
    if (fittedRef.current === fitKey) return;

    const [west, south, east, north] = mapBounds;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 36, duration: 0, maxZoom: 19 },
    );
    fittedRef.current = fitKey;
  }, [mapBounds, mapReady, realLocator, effectiveFarmId]);

  const comparisonEnabled =
    Boolean(data?.comparison.enabled) &&
    dates.length >= (data?.comparison.minimum_dates ?? 2) &&
    selectedDate !== "" &&
    comparisonDate !== "" &&
    selectedDate !== comparisonDate;

  const toggleLayer = (layerType: MapLayerType) => {
    setSelectedLayers((current) => {
      const next = new Set(current);
      if (next.has(layerType)) next.delete(layerType);
      else next.add(layerType);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div className="status-banner status-banner-info">
        <div className="font-medium">
          {isPlotTimeline(data)
            ? "Mapa histórico de tu finca"
            : "Mapa de la finca"}
        </div>
        <p className="mt-1 text-sm">
          {isPlotTimeline(data)
            ? "Elige una fecha y activa las capas disponibles para explorar tu finca. Fuera de la ortofoto puedes ver el fondo satelital si Google Maps está habilitado."
            : "Los levantamientos aparecerán cuando estén disponibles en tu cuenta."}
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="card space-y-5">
          <div>
            <div className="eyebrow">Finca / lote</div>
            <h2 className="mt-1 text-lg font-semibold">{realLocator ? farmLabel : "Mapa de finca"}</h2>
            {isPlotTimeline(data) && (
              <p className="muted mt-1 text-sm">Lote: {plotLabel}</p>
            )}

          </div>

          <div className="divider pt-4">
            <label className="text-sm font-medium" htmlFor="map-date">
              Fecha principal
            </label>
            <select
              id="map-date"
              className="mt-2 w-full"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              disabled={dates.length === 0}
            >
              <option value="">
                {dates.length === 0 ? "Sin campañas registradas" : "Todas las fechas"}
              </option>
              {dates.map((date) => (
                <option key={date} value={date}>
                  {formatDate(date)}
                </option>
              ))}
            </select>
          </div>

          <div className="divider pt-4">
            <div className="text-sm font-medium">Capas</div>
            <div className="mt-3 space-y-3">
              {(data?.available_layers ?? []).map((layer) => {
                const available = availableLayerTypes.has(layer.layer_type);
                return (
                  <label
                    key={layer.layer_type}
                    className="flex items-start gap-3 text-sm"
                  >
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedLayers.has(layer.layer_type)}
                      disabled={!available}
                      onChange={() => toggleLayer(layer.layer_type)}
                    />
                    <span>
                      <span className="font-medium">
                        {layer.label}
                        {!available && <span className="muted"> · sin datos</span>}
                      </span>
                      <span className="muted mt-0.5 block">
                        {layer.description}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          {realLocator && (
            <div className="divider space-y-3 pt-4">
              <div className="text-sm font-semibold">Resultados GIS del levantamiento</div>
              <p className="muted text-xs">Activa las capas y pulsa un elemento del mapa para consultar sus datos.</p>
              {campaignLoadError ? (
                <p role="alert" className="text-sm text-rose-600">No se pudo consultar las campañas agrícolas autorizadas.</p>
              ) : visibleVectorMeta.length === 0 ? (
                <p className="muted text-sm">Todavía no hay capas GIS publicadas en esta fecha.</p>
              ) : visibleVectorMeta.map(layer => (
                <label key={layer.id} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedVectorIds.has(layer.id)}
                    onChange={() => setSelectedVectorIds(current => {
                      const next = new Set(current);
                      if (next.has(layer.id)) next.delete(layer.id);
                      else next.add(layer.id);
                      return next;
                    })}
                  />
                  <span>
                    <span className="flex items-center gap-2">
                      <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full border border-white/70"
                        style={{ backgroundColor: GIS_KIND_COLORS[layer.layer_kind] }} />
                      <span className="font-medium">{layer.name}</span>
                    </span>
                    <span className="muted block text-xs">
                      {GIS_KIND_LABELS[layer.layer_kind]} · {layer.feature_count} elementos
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}

          {canPublish && realLocator && (
            <div className="divider space-y-3 pt-4">
              <div className="text-sm font-semibold">Añadir resultado cartográfico</div>
              <p className="muted text-xs">GeoJSON (hasta 2 MiB) se publica directamente. GeoPackage o Shapefile ZIP (hasta 30 MiB) se reciben de forma privada y quedan pendientes de conversión y revisión.</p>
              <label htmlFor="dbi-upload-campaign" className="block text-xs font-medium">Levantamiento al que pertenece la capa</label>
              <select id="dbi-upload-campaign" className="w-full" value={chosenUploadCampaign}
                onChange={event => setChosenUploadCampaign(event.target.value)}>
                <option value="">Selecciona un levantamiento real</option>
                {uploadCampaignChoices.map(campaign => (
                  <option key={campaign.id} value={campaign.id}>
                    {formatDate(campaign.captured_at)} · {campaign.analysis_type === "density" ? "Densidad" : "Multiespectral"} · {campaign.name}
                  </option>
                ))}
              </select>
              {uploadCampaignChoices.length === 0 && (
                <p className="muted text-xs">
                  {campaignLoadError
                    ? "No se pudieron consultar los levantamientos. Verifica la conexión."
                    : "No hay un levantamiento técnico en esta fecha. Selecciona otra fecha para publicar."}
                </p>
              )}
              <select className="w-full" aria-label="Tipo de capa" value={uploadKind}
                onChange={event => setUploadKind(event.target.value as VectorLayerKind)}>
                <option value="density_hexagons">Densidad por sectores</option>
                <option value="plants">Ubicación de plantas</option>
                <option value="planting_candidates">Oportunidades de siembra</option>
                <option value="boundaries">Límites</option>
                <option value="observations">Inspecciones</option>
                <option value="other">Otra información GIS</option>
              </select>
              <input aria-label="Seleccionar GeoJSON" type="file" accept=".geojson,.json,.gpkg,.zip,application/geo+json"
                className="block w-full text-xs" onChange={event => setUploadFile(event.target.files?.[0] ?? null)} />
              <button type="button" className="btn-primary w-full"
                disabled={!uploadFile || !uploadCampaignId || uploading}
                onClick={() => void uploadSelectedGeoJSON()}>
                {uploading ? "Procesando recepción…" : /\.(zip|gpkg)$/i.test(uploadFile?.name ?? "") ? "Guardar original privado" : "Publicar GeoJSON en el lote"}
              </button>
              {uploadNotice && <p role="status" className="muted text-xs">{uploadNotice}</p>}
              {gisImports.length > 0 && (
                <div className="space-y-2" aria-label="Archivos GIS recibidos">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium">Archivos GIS y estado de revisión</p>
                    <button
                      type="button"
                      className="text-xs font-medium underline disabled:opacity-50"
                      onClick={() => void refreshGISImportStatus()}
                      disabled={gisRefreshBusy}
                      aria-label="Actualizar estados de archivos GIS"
                    >
                      {gisRefreshBusy ? "Actualizando…" : "Actualizar"}
                    </button>
                  </div>
                  {hasPendingGISImports && (
                    <p className="muted text-xs">Los estados pendientes se actualizan automáticamente cada 15 segundos mientras esta página esté abierta.</p>
                  )}
                  {gisImports.slice(0, 8).map(item => (
                    <div key={item.id} className="space-y-2 rounded-lg border border-slate-300/40 p-2 text-xs">
                      <span className="block font-medium">{item.original_filename}</span>
                      <span className="muted block">
                        {item.status === "received" ? "Recibido · pendiente de conversión"
                          : item.status === "processing" ? "En conversión"
                          : item.status === "prepared" ? "Convertido · pendiente de aprobación"
                          : item.status === "published" ? "Revisado · publicado en el lote"
                          : "Conversión fallida"}
                      </span>
                      {item.status === "prepared" && (
                        <button type="button" className="text-xs font-medium underline"
                          disabled={gisReviewBusy}
                          onClick={() => void inspectGISImport(item)}>
                          Revisar vista previa en el mapa
                        </button>
                      )}
                      {item.status === "prepared" && reviewedImportId === item.id
                        && gisPreviewVector && (
                          <div className="space-y-2 border-t border-slate-300/40 pt-2">
                            <p className="muted">
                              Vista previa privada: {gisPreviewVector.layer.feature_count} elementos.
                              Confirma geometrías, atributos y fecha del levantamiento.
                            </p>
                            <button type="button" className="btn-primary w-full"
                              disabled={gisReviewBusy || !activeCampaignIds.has(item.campaign_id)}
                              onClick={() => void approveGISImport(item)}>
                              {gisReviewBusy ? "Publicando…" : "Aprobar y publicar esta capa"}
                            </button>
                          </div>
                        )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="divider pt-4">
            <label className="text-sm font-medium" htmlFor="comparison-date">
              Comparar con
            </label>
            <select
              id="comparison-date"
              className="mt-2 w-full"
              value={comparisonDate}
              onChange={(event) => setComparisonDate(event.target.value)}
              disabled={!data?.comparison.enabled || dates.length < 2}
            >
              <option value="">Selecciona otra fecha</option>
              {dates.map((date) => (
                <option key={date} value={date}>
                  {formatDate(date)}
                </option>
              ))}
            </select>
            <p className="muted mt-2">
              {comparisonEnabled
                ? "Las dos fechas existen; la comparación visual avanzada se habilitará sin alterar sus fuentes."
                : "Se requieren dos fechas reales distintas."}
            </p>
          </div>
        </aside>

        <section className="card p-0 overflow-hidden">
          <div className="relative min-h-[560px]">
            {useGoogleBase && realLocator ? (
              <GoogleSatelliteViewer
                tenantRef={realLocator.tenantRef}
                entries={displayEntries}
                bounds={mapBounds}
                vectors={visibleVectorDetails}
              />
            ) : (
              <div
                ref={mapContainerRef}
                className="absolute inset-0"
                aria-label="Mapa cronológico de la finca"
              />
            )}

            <div className="pointer-events-none absolute inset-x-4 bottom-4">
              {loading && (
                <div className="status-banner bg-white/95 text-sm shadow-lg dark:bg-dal-petrol/95">
                  Cargando cronología cartográfica…
                </div>
              )}

              {!loading && error && (
                <div className="status-banner status-banner-danger pointer-events-auto text-sm shadow-lg">
                  {error}
                </div>
              )}

              {!loading && !error && visibleEntries.length === 0 && visibleVectorDetails.length === 0 && (
                <div className="empty-state pointer-events-auto shadow-lg">
                  <div className="font-medium">
                    No hay campañas cartográficas visibles
                  </div>
                  <p className="muted mt-2">
                    No se muestran geometrías, índices ni recomendaciones
                    simuladas. Las capas aparecen únicamente cuando existe
                    evidencia real autorizada para este lote.
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
