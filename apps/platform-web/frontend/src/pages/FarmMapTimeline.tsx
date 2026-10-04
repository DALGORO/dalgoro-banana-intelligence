import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
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

  const realLocator = useMemo(() => {
    if (!organizationRef || !farmId || !plotId || !tenantRef) return null;
    return {
      tenantRef,
      organizationRef,
      farmId,
      plotId,
    };
  }, [farmId, organizationRef, plotId, tenantRef]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

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
      fittedRef.current = null;
      setMapReady(false);
    };
  }, [tenantRef]);

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

  const dates = useMemo(
    () =>
      Array.from(
        new Set((data?.timeline ?? []).map((entry) => entry.captured_at)),
      ).sort(),
    [data?.timeline],
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
          (selectedDate === "" || entry.captured_at === selectedDate),
      ),
    [data?.timeline, selectedDate, selectedLayers],
  );

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
  }, [displayEntries, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !isPlotTimeline(data) || !data.viewport_bounds) {
      return;
    }

    const fitKey = [
      data.plot_id,
      ...data.viewport_bounds.map((value) => value.toFixed(7)),
    ].join(":");
    if (fittedRef.current === fitKey) return;

    const [west, south, east, north] = data.viewport_bounds;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 36, duration: 0, maxZoom: 19 },
    );
    fittedRef.current = fitKey;
  }, [data, mapReady]);

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
            ? "Visor cronológico Raster DBI"
            : "Visor cronológico v1"}
        </div>
        <p className="mt-1 text-sm">
          {isPlotTimeline(data)
            ? "Las imágenes visibles provienen de campañas reales y tiles privados autorizados; el navegador no recibe la ruta del COG."
            : "El catálogo indica qué capas admite la plataforma. Una capa solo aparecerá cuando exista una campaña real registrada."}
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="card space-y-5">
          <div>
            <div className="eyebrow">Finca / lote</div>
            <h2 className="mt-1 break-all">{effectiveFarmId || "Sin identificar"}</h2>
            {isPlotTimeline(data) && (
              <p className="muted mt-1 break-all text-xs">Lote: {data.plot_id}</p>
            )}
            <p className="muted mt-2">
              Contrato: {data?.schema_version ?? "pendiente de carga"}
            </p>
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
                {dates.length === 0 ? "Sin campañas registradas" : "Más reciente por capa"}
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
            <div
              ref={mapContainerRef}
              className="absolute inset-0"
              aria-label="Mapa cronológico de la finca"
            />

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

              {!loading && !error && visibleEntries.length === 0 && (
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
