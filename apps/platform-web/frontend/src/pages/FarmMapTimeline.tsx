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
import { Layers3, MapPinned } from "lucide-react";
import { GoogleSatelliteViewer } from "@/components/GoogleSatelliteViewer";
import { MultispectralEvidencePanel } from "@/components/MultispectralEvidencePanel";
import { FarmTrackingPanel } from "@/components/FarmTrackingPanel";
import { belongsToSelectedMapCampaign, mapTimelineViewKey } from "@/features/mapCampaignSelection";
import { producerMapVisits, visitsAtDate } from "@/features/producerMapVisits";
import { api } from "@/app/api";
import {
  getVectorLayer, listVectorLayers, listVectorCampaigns, listManagementCampaigns, listGISImports, getGISImportPreview, publishReviewedGISImport, publishGeoJSON, stageGISOriginal, selectGISImportLayer, vectorExtent,
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

function FarmMapTimelineView() {
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
  const [infoTab, setInfoTab] = useState<"multi" | "tracking">("tracking");
  const manuallySelectedVisitRef = useRef(false);
  const [specificMapCampaign, setSpecificMapCampaign] = useState<{
    scopeKey: string; campaignId: string;
  } | null>(null);
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
  const [gisChoice, setGISChoice] = useState<{ scopeKey: string; values: Record<string, string> } | null>(null);
  const [gisChoiceBusyId, setGISChoiceBusyId] = useState<string | null>(null);
  const [reviewedImportId, setReviewedImportId] = useState<string | null>(null);
  const [gisPreviewVector, setGISPreviewVector] = useState<VectorLayerDetail | null>(null);
  const [gisReviewBusy, setGISReviewBusy] = useState(false);
  const [vectorCampaigns, setVectorCampaigns] = useState<VectorCampaign[]>([]);
  const [managementCampaigns, setManagementCampaigns] = useState<VectorCampaign[]>([]);
  const [publishBusyId, setPublishBusyId] = useState<string | null>(null);
  const [publishNotice, setPublishNotice] = useState<string | null>(null);
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
    ? JSON.stringify([realLocator.tenantRef, realLocator.organizationRef, realLocator.farmId, realLocator.plotId])
    : "";
  const selectedMapCampaignId = specificMapCampaign?.scopeKey === gisScopeKey
    ? specificMapCampaign.campaignId : null;
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
  }, [realLocator, gisScopeKey]);


  // Los archivos GIS en preparación son privados: el endpoint exige MANAGE,
  // por lo que una cuenta exclusivamente READ nunca debe consultarlo.
  useEffect(() => {
    if (!realLocator || !canPublish) return;
    let active = true;
    listManagementCampaigns(realLocator).then(rows => {
      if (active) setManagementCampaigns(rows);
    }).catch(() => {
      if (active) setManagementCampaigns([]);
    });
    listGISImports(realLocator).then(receipts => {
      if (active) setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
    }).catch(() => {
      if (active) setGISImportCache({ scopeKey: gisScopeKey, items: [] });
    });
    return () => { active = false; };
  }, [realLocator, gisScopeKey, canPublish]);

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

        // En el mapa scoped, la cronología RGB y GIS selecciona la última Campaign
        // por identidad exacta en el efecto mapVisits. Un HTTP tardío NO debe
        // sobrescribir el levantamiento elegido por el productor.
        if (!realLocator && !manuallySelectedVisitRef.current) {
          const dates = Array.from(
            new Set(response.timeline.map((entry) => entry.captured_at)),
          ).sort();
          setSelectedDate(dates.at(-1) ?? "");
          setSpecificMapCampaign(null);
        }
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

  const mapVisits = useMemo(() => producerMapVisits(
    isPlotTimeline(data) ? data.timeline : [],
    vectorCampaigns, vectorLayers,
  ), [data, vectorCampaigns, vectorLayers]);

  const visitsForDate = useMemo(
    () => visitsAtDate(mapVisits, selectedDate),
    [mapVisits, selectedDate],
  );
  const ambiguousMapDate = Boolean(realLocator && selectedDate
    && !selectedMapCampaignId && visitsForDate.length > 1);

  // La llegada asíncrona de capas GIS puede descubrir un levantamiento más reciente.
  // Solo autoelige mientras el productor no haya tomado el control de la selección.
  useEffect(() => {
    if (!realLocator || manuallySelectedVisitRef.current || mapVisits.length === 0) return;
    const latest = mapVisits[0];
    if (selectedDate !== latest.capturedAt || selectedMapCampaignId !== latest.campaignId) {
      setSelectedDate(latest.capturedAt);
      setSpecificMapCampaign({ scopeKey: gisScopeKey, campaignId: latest.campaignId });
    }
  }, [realLocator, mapVisits, selectedDate, selectedMapCampaignId, gisScopeKey]);

  const dates = useMemo(() => Array.from(new Set([
    ...mapVisits.map(visit => visit.capturedAt),
    ...(selectedMapCampaignId && selectedDate ? [selectedDate] : []),
  ])).sort(), [mapVisits, selectedMapCampaignId, selectedDate]);

  const selectedVisit = mapVisits.find(visit => visit.campaignId === selectedMapCampaignId
    && sameCapture(visit.capturedAt, selectedDate));
  const currentVisitIndex = selectedVisit
    ? mapVisits.indexOf(selectedVisit)
    : mapVisits.findIndex(visit => sameCapture(visit.capturedAt, selectedDate));
  const currentMapVisit = currentVisitIndex >= 0 ? mapVisits[currentVisitIndex] : null;
  const olderVisit = currentVisitIndex >= 0 ? mapVisits[currentVisitIndex + 1] : undefined;
  const newerVisit = currentVisitIndex > 0 ? mapVisits[currentVisitIndex - 1] : undefined;

  const availableLayerTypes = useMemo(
    () => new Set((data?.timeline ?? []).map((entry) => entry.layer_type)),
    [data?.timeline],
  );

  const visibleEntries = useMemo(
    () =>
      (data?.timeline ?? []).filter(
        (entry) =>
          !ambiguousMapDate && (!realLocator || Boolean(selectedDate)) &&
          selectedLayers.has(entry.layer_type) &&
          (isRasterEntry(entry)
            ? belongsToSelectedMapCampaign(entry.captured_at, entry.campaign_id,
                selectedDate, selectedMapCampaignId)
            : !selectedMapCampaignId &&
              (selectedDate === "" || sameCapture(entry.captured_at, selectedDate))),
      ),
    [data?.timeline, selectedDate, selectedLayers, selectedMapCampaignId, ambiguousMapDate, realLocator],
  );


  const activeCampaignIds = useMemo(() => new Set(
    vectorCampaigns
      .filter(campaign => !ambiguousMapDate && (!realLocator || Boolean(selectedDate))
        && belongsToSelectedMapCampaign(
        campaign.captured_at, campaign.id, selectedDate, selectedMapCampaignId,
      ))
      .map(campaign => campaign.id)
  ), [vectorCampaigns, selectedDate, selectedMapCampaignId, ambiguousMapDate, realLocator]);

  const visibleVectorMeta = useMemo(() =>
    vectorLayers.filter(layer => activeCampaignIds.has(layer.campaign_id)),
    [vectorLayers, activeCampaignIds],
  );

  // Las Campaign en revisión sólo autorizan previsualizaciones privadas MANAGE.
  // Nunca intervienen en las capas de producción del productor.
  const managementActiveCampaignIds = useMemo(() => new Set(
    canPublish ? managementCampaigns.filter(campaign =>
      campaign.status !== "PUBLISHED" && belongsToSelectedMapCampaign(
        campaign.captured_at, campaign.id, selectedDate, selectedMapCampaignId,
      ),
    ).map(campaign => campaign.id) : [],
  ), [canPublish, managementCampaigns, selectedDate, selectedMapCampaignId]);

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
    return gisPreviewVector && managementActiveCampaignIds.has(gisPreviewVector.layer.campaign_id)
      ? [...published, gisPreviewVector] : published;
  }, [visibleVectorMeta, selectedVectorIds, vectorDetails, gisPreviewVector, managementActiveCampaignIds]);

  const uploadCampaignChoices = useMemo(() =>
    managementCampaigns.filter(campaign => belongsToSelectedMapCampaign(
      campaign.captured_at, campaign.id, selectedDate, selectedMapCampaignId,
    )),
    [managementCampaigns, selectedDate, selectedMapCampaignId],
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
    let inFlight = false;
    const interval = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void listGISImports(realLocator).then(receipts => {
        if (active) setGISImportCache({ scopeKey: gisScopeKey, items: receipts });
      }).catch(() => {
        // Conserva el último estado conocido; se volverá a intentar.
      }).finally(() => {
        inFlight = false;
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
      setSpecificMapCampaign({ scopeKey: gisScopeKey, campaignId: item.campaign_id });
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
        || !gisPreviewVector || !managementActiveCampaignIds.has(item.campaign_id)) return;
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

  async function saveGISLayerChoice(item: GISImportReceipt) {
    const layer = gisChoice?.scopeKey === gisScopeKey ? gisChoice.values[item.id] : undefined;
    if (!realLocator || !canPublish || item.status !== "needs_selection"
      || item.selected_layer || !layer || !item.available_layers?.includes(layer)
      || gisChoiceBusyId) return;
    setGISChoiceBusyId(item.id);
    setUploadNotice(null);
    try {
      await selectGISImportLayer(realLocator, item.id, layer);
      setGISImportCache({ scopeKey: gisScopeKey, items: await listGISImports(realLocator) });
      setUploadNotice("Elección guardada. La conversión de esa capa aún no está habilitada.");
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setUploadNotice(typeof detail === "string" ? detail : "No se pudo guardar la elección GIS.");
    } finally {
      setGISChoiceBusyId(null);
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

  // El acceso rápido móvil y el selector lateral comparten la misma regla:
  // elegir una fecha elimina la restricción de ID Campaign, sin inventar vínculo.
  const selectPrimaryMapDate = (date: string) => {
    manuallySelectedVisitRef.current = true;
    setSelectedDate(date);
    setSpecificMapCampaign(null);
  };

  const chooseMapVisit = (campaignId: string, capturedAt: string) => {
    const visit = mapVisits.find(item => item.campaignId === campaignId
      && sameCapture(item.capturedAt, capturedAt));
    if (!visit) return;
    manuallySelectedVisitRef.current = true;
    setSelectedDate(visit.capturedAt);
    setSpecificMapCampaign({ scopeKey: gisScopeKey, campaignId: visit.campaignId });
    setComparisonDate("");
  };

  const publishInstitutionally = async (campaignId: string) => {
    if (!realLocator || !canPublish || publishBusyId) return;
    const chosen = managementCampaigns.find(row => row.id === campaignId);
    if (!chosen || chosen.status !== "APPROVED") return;
    setPublishBusyId(campaignId);
    setPublishNotice(null);
    try {
      const root = [
        "/api/v1/dbi/organizations", encodeURIComponent(realLocator.organizationRef),
        "farms", encodeURIComponent(realLocator.farmId),
        "plots", encodeURIComponent(realLocator.plotId),
      ].join("/");
      await api.post(
        `${root}/campaigns/${encodeURIComponent(campaignId)}/transitions`,
        { status: "PUBLISHED" },
        { headers: { "X-DBI-Tenant": realLocator.tenantRef } },
      );
      const [publishedCampaigns, publishedLayers, current, management] = await Promise.all([
        listVectorCampaigns(realLocator),
        listVectorLayers(realLocator),
        getPlotMapTimeline(realLocator),
        listManagementCampaigns(realLocator),
      ]);
      setVectorCampaigns(publishedCampaigns);
      setVectorLayers(publishedLayers);
      setSelectedVectorIds(new Set(publishedLayers.map(layer => layer.id)));
      setManagementCampaigns(management);
      setData(current);
      setPublishNotice("Publicación institucional registrada. El cliente ya puede consultar las evidencias aprobadas.");
    } catch (error) {
      const code = (error as { response?: { status?: number } })?.response?.status;
      setPublishNotice(code === 404
        ? "No autorizado: se requiere acreditación activa como administrador institucional DALGORO y permisos sobre el lote."
        : "No se pudo publicar la campaña. Comprueba que la revisión técnica está completa.");
    } finally {
      setPublishBusyId(null);
    }
  };

  const toggleLayer = (layerType: MapLayerType) => {
    setSelectedLayers((current) => {
      const next = new Set(current);
      if (next.has(layerType)) next.delete(layerType);
      else next.add(layerType);
      return next;
    });
  };

  return (
    <div className="dbi-map-workspace space-y-4">
      <div className="dbi-map-intro">
        <span className="dbi-section-icon" aria-hidden="true"><MapPinned size={22} /></span>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">DALGORO · Visor agrícola privado</div>
          <h2 className="mt-1 text-lg font-semibold">
            {realLocator ? `${farmLabel} · ${plotLabel}` : "Mapa de la finca"}
          </h2>
          <p className="muted mt-1 text-sm">
            Explora los levantamientos de tu lote por fecha. El mapa muestra únicamente
            fotografías y capas cartográficas realmente disponibles para tu cuenta.
          </p>
        </div>
        <div className="dbi-map-intro-meta" aria-label="Estado del mapa">
          <span className="dbi-info-chip"><Layers3 size={15} aria-hidden="true" />
            {visibleEntries.length} fotos RGB · {visibleVectorDetails.length} capas GIS visibles
          </span>
          {selectedMapCampaignId && (
            <span className="dbi-info-chip dbi-info-chip-accent">
              Levantamiento específico seleccionado
            </span>
          )}
        </div>
        <nav className="dbi-mobile-toolbar" aria-label="Accesos rápidos del visor">
          <label className="block text-xs font-semibold" htmlFor="dbi-mobile-date">
            Fecha principal del mapa
          </label>
          <select
            id="dbi-mobile-date"
            className="w-full"
            value={selectedDate}
            disabled={dates.length === 0}
            onChange={(event) => selectPrimaryMapDate(event.target.value)}
          >
            <option value="">
              {dates.length === 0 ? "Sin levantamientos con mapa" : "Elegir un levantamiento"}
            </option>
            {dates.map(date => (
              <option key={date} value={date}>
                {formatDate(date)}
                {selectedMapCampaignId && sameCapture(selectedDate, date)
                  ? " · Levantamiento elegido" : ""}
              </option>
            ))}
          </select>
          <div className="dbi-mobile-shortcuts">
            <a href="#dbi-map-view">Ir al mapa</a>
            <a href="#dbi-tab-tracking" onClick={() => setInfoTab("tracking")}>Ficha del lote</a>
            {realLocator && <a href="#dbi-multi-evidence" onClick={() => setInfoTab("multi")}>Ver evidencia MULTI</a>}
          </div>
          <p className="muted text-xs">
            Si una fecha tiene varios levantamientos, elígelos por separado en el historial.
          </p>
        </nav>
      </div>

      <div className="dbi-visual-grid">
        <aside id="dbi-map-controls" className="card dbi-map-controls space-y-5">
          <div>
            <div className="eyebrow">Opciones de visualización</div>
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
              onChange={(event) => selectPrimaryMapDate(event.target.value)}
              disabled={dates.length === 0}
            >
              <option value="">
                {dates.length === 0 ? "Sin levantamientos con mapa" : "Elegir un levantamiento"}
              </option>
              {dates.map((date) => (
                <option key={date} value={date}>
                  {formatDate(date)}
                  {selectedMapCampaignId && sameCapture(selectedDate, date)
                    ? " · Levantamiento elegido" : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="divider pt-4">
            <div className="text-sm font-medium">Mostrar en el mapa</div>
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
            <section className="divider space-y-2 pt-4" aria-label="Seis mapas multiespectrales">
              <div className="text-sm font-semibold">Mapas de los seis índices</div>
              <p className="muted text-xs">
                Los seis índices están calculados como estadísticas de muestras.
                Sus mapas georreferenciados aún no tienen productos cartográficos
                individualizados aprobados para mostrar. Consulta los valores
                reales en «Índices y muestras».
              </p>
              <div className="dbi-six-index-switches">
                {["NDVI", "NDRE", "GNDVI", "EVI2", "CI Red Edge", "CI Green"].map(label => (
                  <label key={label} className="dbi-index-switch" title="Mapa no disponible hasta aprobar un ráster temático verificable">
                    <input type="checkbox" disabled aria-label={`Mapa ${label} pendiente de publicación`} />
                    <span>{label} · Sin mapa</span>
                  </label>
                ))}
              </div>
              <button type="button" className="btn-secondary"
                onClick={() => {
                  setInfoTab("multi");
                  document.getElementById("dbi-tab-multi")?.scrollIntoView({ block: "start" });
                }}>Consultar las seis estadísticas disponibles</button>
            </section>
          )}

          {realLocator && (
            <div className="divider space-y-3 pt-4">
              <div className="text-sm font-semibold">Población y resultados GIS del levantamiento</div>
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
            <details className="divider dbi-manage-details pt-4">
              <summary className="cursor-pointer text-sm font-semibold">Gestionar y publicar capas GIS</summary>
              <div className="space-y-3 pt-3">
                <p className="muted text-xs">
                  Los gestores pueden preparar archivos privados. La publicación final solo
                  corresponde al administrador institucional DALGORO acreditado.
                </p>
                <section className="space-y-2 rounded-xl border border-slate-200 p-3 dark:border-slate-700"
                  aria-label="Aprobación institucional de levantamientos">
                  <h3 className="font-semibold text-sm">Aprobación para mostrar al cliente</h3>
                  <p className="muted text-xs">
                    Una campaña debe completar las verificaciones y llegar a APPROVED antes
                    de permitir su publicación. Esta acción se valida nuevamente en el servidor.
                  </p>
                  {managementCampaigns.filter(row => row.status === "APPROVED").map(row => (
                    <div key={row.id} className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs">
                        {formatDate(row.captured_at)} · {row.name} · Aprobada técnicamente
                      </span>
                      <button className="btn-secondary" type="button"
                        disabled={publishBusyId !== null}
                        onClick={() => void publishInstitutionally(row.id)}>
                        {publishBusyId === row.id ? "Verificando autoridad…" : "Publicar al cliente"}
                      </button>
                    </div>
                  ))}
                  {!managementCampaigns.some(row => row.status === "APPROVED") &&
                    <p className="muted text-xs">No hay levantamientos aprobados pendientes de publicación.</p>}
                  {publishNotice && <p role="status" className="text-xs">{publishNotice}</p>}
                </section>
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
                          : item.status === "needs_selection" ? (item.selected_layer ? "Capa elegida · pendiente de conversión" : "Capas detectadas · pendiente de elección")
                          : item.status === "prepared" ? "Convertido · pendiente de aprobación"
                          : item.status === "published" ? "Revisado · publicado en el lote"
                          : "Conversión fallida"}
                      </span>
                      {item.status === "needs_selection" && item.selected_layer && (
                        <span className="muted block">
                          Capa seleccionada: <strong>{item.selected_layer}</strong>. Todavía no se ha convertido ni publicado.
                        </span>
                      )}
                      {item.status === "needs_selection" && !item.selected_layer && item.available_layers && (
                        <div className="space-y-2">
                          <label htmlFor={`dbi-layer-choice-${item.id}`} className="block font-medium">
                            Elegir una capa geométrica del GeoPackage
                          </label>
                          <select
                            id={`dbi-layer-choice-${item.id}`}
                            className="w-full"
                            value={gisChoice?.scopeKey === gisScopeKey ? (gisChoice.values[item.id] ?? "") : ""}
                            disabled={gisChoiceBusyId !== null}
                            onChange={event => setGISChoice(current => ({
                              scopeKey: gisScopeKey,
                              values: {
                                ...(current?.scopeKey === gisScopeKey ? current.values : {}),
                                [item.id]: event.target.value,
                              },
                            }))}
                          >
                            <option value="">Selecciona una capa detectada</option>
                            {item.available_layers.map(layer => (
                              <option key={layer} value={layer}>{layer}</option>
                            ))}
                          </select>
                          <button type="button" className="btn-primary w-full"
                            disabled={gisChoiceBusyId !== null
                              || !item.available_layers.includes(
                                gisChoice?.scopeKey === gisScopeKey ? (gisChoice.values[item.id] ?? "") : "",
                              )}
                            onClick={() => void saveGISLayerChoice(item)}>
                            {gisChoiceBusyId === item.id ? "Guardando elección…" : "Guardar elección de capa"}
                          </button>
                          <p className="muted">La elección será única. Guardarla no inicia conversión ni publicación.</p>
                        </div>
                      )}
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
                              disabled={gisReviewBusy || !managementActiveCampaignIds.has(item.campaign_id)}
                              onClick={() => void approveGISImport(item)}>
                              {gisReviewBusy ? "Publicando…" : "Aprobar y publicar esta capa"}
                            </button>
                          </div>
                        )}
                    </div>
                  ))}
                  {gisImports.length === 0 && (
                    <p className="muted text-xs">No hay originales GIS recibidos en este lote.</p>
                  )}
                </div>
              </div>
            </details>
          )}

          <div className="divider pt-4">
            <label className="text-sm font-medium" htmlFor="comparison-date">
              Comparación por fechas (próximamente)
            </label>
            <select
              id="comparison-date"
              className="mt-2 w-full"
              value={comparisonDate}
              onChange={(event) => setComparisonDate(event.target.value)}
              disabled
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
                ? "Hay dos fechas registradas, pero todavía no existe una comparación cartográfica validada. Revisa los levantamientos uno por uno."
                : "El comparador cartográfico todavía no está disponible. Utiliza Anterior y Siguiente para consultar cada levantamiento por separado."}
            </p>
          </div>
        </aside>

        <section id="dbi-map-view" className="card dbi-map-stage p-0 overflow-hidden" aria-label="Mapa de la campaña seleccionada">
          <div className="relative min-h-[560px]">
            <div className="dbi-map-stage-label" aria-label="Fecha del mapa">
              <MapPinned size={16} aria-hidden="true" />
              <span>{selectedDate ? formatDate(selectedDate) : "Selecciona un levantamiento"}</span>
              {currentMapVisit && <span className="dbi-map-stage-kind">
                {currentMapVisit.hasRgb ? "Fotografía RGB" : "Cartografía GIS"}
              </span>}
            </div>
            {(displayEntries.length > 0 || visibleVectorDetails.length > 0) && (
              <div className="dbi-map-legend" aria-label="Leyenda de capas visibles">
                <strong>Capas del levantamiento</strong>
                {displayEntries.length > 0 && (
                  <span><i className="dbi-legend-rgb" aria-hidden="true" /> Imagen aérea RGB</span>
                )}
                {visibleVectorDetails.slice(0, 4).map(vector => (
                  <span key={vector.layer.id}>
                    <i aria-hidden="true" style={{ backgroundColor: GIS_KIND_COLORS[vector.layer.layer_kind] }} />
                    {GIS_KIND_LABELS[vector.layer.layer_kind]}
                  </span>
                ))}
                {visibleVectorDetails.length > 4 && <small>Más capas en Opciones de visualización</small>}
              </div>
            )}
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
                    {ambiguousMapDate
                      ? "Hay varios levantamientos en esta fecha"
                      : selectedMapCampaignId
                        ? "Este levantamiento no tiene capas cartográficas disponibles"
                        : "Selecciona un levantamiento del historial"}
                  </div>
                  <p className="muted mt-2">
                    {ambiguousMapDate
                      ? "Elige un levantamiento concreto de la línea de tiempo para evitar mezclar vuelos diferentes."
                      : "No hay cartografía autorizada para mostrar en esta selección. No se simulan imágenes ni resultados."}
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>
        <section id="dbi-map-history" className="dbi-map-history" aria-label="Historial cartográfico de levantamientos">
          <div className="dbi-map-history-heading">
            <div>
              <div className="eyebrow">Trazabilidad por fecha</div>
              <h3 className="mt-1 text-base font-semibold">Historial de levantamientos</h3>
            </div>
            <span className="muted text-xs">{mapVisits.length} con cartografía disponible</span>
          </div>
          {mapVisits.length > 0 ? (
            <div className="dbi-map-history-nav">
              <button type="button" className="dbi-history-arrow"
                disabled={!olderVisit} onClick={() => olderVisit && chooseMapVisit(olderVisit.campaignId, olderVisit.capturedAt)}
                aria-label="Ver levantamiento anterior">← Anterior</button>
              <div className="dbi-map-history-strip" role="group" aria-label="Elegir levantamiento por fecha">
                {[...mapVisits].reverse().map(visit => {
                  const active = selectedMapCampaignId === visit.campaignId
                    && sameCapture(selectedDate, visit.capturedAt);
                  return (
                    <button type="button" key={visit.campaignId}
                      className="dbi-map-history-visit" aria-pressed={active}
                      onClick={() => chooseMapVisit(visit.campaignId, visit.capturedAt)}>
                      <span className="dbi-history-dot" aria-hidden="true" />
                      <strong>{formatDate(visit.capturedAt)}</strong>
                      <span className="dbi-history-visit-name">{visit.name}</span>
                      <small>{visit.hasRgb ? "Fotografía RGB" : "Capas GIS"}
                        {visit.gisLayerCount > 0 ? ` · ${visit.gisLayerCount} capas GIS` : ""}</small>
                    </button>
                  );
                })}
              </div>
              <button type="button" className="dbi-history-arrow"
                disabled={!newerVisit} onClick={() => newerVisit && chooseMapVisit(newerVisit.campaignId, newerVisit.capturedAt)}
                aria-label="Ver levantamiento siguiente">Siguiente →</button>
            </div>
          ) : (
            <p className="muted text-sm">Este lote aún no tiene levantamientos con cartografía autorizada para consultar.</p>
          )}
          {currentMapVisit && (
            <p className="dbi-map-history-note">
              {currentMapVisit.reviewStatus === "approved"
                ? "Imagen RGB con revisión profesional aprobada."
                : currentMapVisit.hasRgb
                  ? "Imagen RGB disponible; no implica que el análisis técnico esté aprobado."
                  : "Capas GIS publicadas para consulta. La aprobación técnica del vuelo no se informa aquí."}
              {" "}Cada fecha se consulta por separado; no se comparan automáticamente valores de distintos vuelos.
            </p>
          )}
          {!useGoogleBase && (
            <p className="muted text-xs">
              Fondo satelital no configurado. Se muestran las capas reales que estén disponibles; el fondo neutro no es una ortofoto.
            </p>
          )}
        </section>
      <section className="dbi-info-tabs" aria-label="Información y seguimiento del lote">
        <div className="dbi-info-tab-buttons" role="tablist" aria-label="Pestañas de información agrícola">
          <button
            type="button"
            role="tab"
            id="dbi-tab-multi"
            aria-controls="dbi-panel-multi"
            aria-selected={infoTab === "multi"}
            tabIndex={infoTab === "multi" ? 0 : -1}
            onClick={() => setInfoTab("multi")}
            onKeyDown={event => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              event.preventDefault();
              setInfoTab("tracking");
              document.getElementById("dbi-tab-tracking")?.focus();
            }}
          >
            Índices y muestras
          </button>
          <button
            type="button"
            role="tab"
            id="dbi-tab-tracking"
            aria-controls="dbi-panel-tracking"
            aria-selected={infoTab === "tracking"}
            tabIndex={infoTab === "tracking" ? 0 : -1}
            onClick={() => setInfoTab("tracking")}
            onKeyDown={event => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              event.preventDefault();
              setInfoTab("multi");
              document.getElementById("dbi-tab-multi")?.focus();
            }}
          >
            Resumen del lote
          </button>
        </div>
        <div
          id="dbi-panel-multi"
          role="tabpanel"
          aria-labelledby="dbi-tab-multi"
          className="dbi-info-tab-panel"
          hidden={infoTab !== "multi"}
        >
          {realLocator ? (
            <MultispectralEvidencePanel
              key={gisScopeKey}
              locator={realLocator}
              selectedMapDate={selectedDate}
              selectedMapCampaignId={selectedMapCampaignId}
              onChooseVerifiedCampaign={(campaignId, capturedAt) => {
                manuallySelectedVisitRef.current = true;
                setSpecificMapCampaign({ scopeKey: gisScopeKey, campaignId });
                setSelectedDate(capturedAt);
                setComparisonDate("");
              }}
              onClearMapSelection={() => {
                manuallySelectedVisitRef.current = true;
                setSpecificMapCampaign(null);
                setSelectedDate("");
                setComparisonDate("");
              }}
            />
          ) : (
            <p className="muted p-4 text-sm">
              La evidencia MULTI requiere una ruta privada con tenant, organización, finca y lote.
            </p>
          )}
        </div>
        <div
          id="dbi-panel-tracking"
          role="tabpanel"
          aria-labelledby="dbi-tab-tracking"
          className="dbi-info-tab-panel"
          hidden={infoTab !== "tracking"}
        >
          <FarmTrackingPanel
            farmName={farmLabel}
            plotName={plotLabel}
            selectedMapDate={selectedDate}
            selectedCampaignId={selectedMapCampaignId}
            visibleMapEntries={visibleEntries}
            associatedGISLayers={visibleVectorMeta}
            loading={loading}
            timelineError={error}
            hasScopedPlot={Boolean(realLocator)}
            locator={realLocator}
            onOpenEvidence={() => {
              setInfoTab("multi");
              document.getElementById("dbi-tab-multi")?.focus();
            }}
          />
        </div>
      </section>
      </div>
    </div>
  );
}

/**
 * El router puede reutilizar el mismo componente al cambiar de lote.
 * Key por ámbito fuerza desmontaje antes de que antiguos datos asíncronos
 * o capas/controles administrativos puedan renderizarse en otro ámbito.
 */
export default function FarmMapTimeline() {
  const { fincaId, organizationRef, farmId, plotId } = useParams<{
    fincaId?: string;
    organizationRef?: string;
    farmId?: string;
    plotId?: string;
  }>();
  const [searchParams] = useSearchParams();
  const key = mapTimelineViewKey({
    tenantRef: searchParams.get("tenant")?.trim() ?? "",
    organizationRef,
    farmId,
    plotId,
    fincaId,
  });
  return <FarmMapTimelineView key={key} />;
}
