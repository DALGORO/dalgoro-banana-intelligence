import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Map,
  NavigationControl,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import {
  getFarmMapTimeline,
  type FarmMapTimelineResponse,
  type MapLayerType,
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

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("es-EC");
}

export default function FarmMapTimeline() {
  const { fincaId } = useParams<{ fincaId: string }>();
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);

  const [data, setData] = useState<FarmMapTimelineResponse | null>(null);
  const [selectedLayers, setSelectedLayers] = useState<Set<MapLayerType>>(
    new Set(),
  );
  const [selectedDate, setSelectedDate] = useState("");
  const [comparisonDate, setComparisonDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new Map({
      container: mapContainerRef.current,
      style: EMPTY_MAP_STYLE,
      center: [0, 0],
      zoom: 1,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    let active = true;

    if (!fincaId) {
      setError("No se recibió un identificador de finca válido.");
      setLoading(false);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    setError(null);

    getFarmMapTimeline(fincaId)
      .then((response) => {
        if (!active) return;
        setData(response);
        setSelectedLayers(
          new Set(response.available_layers.map((layer) => layer.layer_type)),
        );
      })
      .catch((requestError) => {
        if (!active) return;
        setError(
          requestError?.response?.data?.detail ??
            "No se pudo cargar la cronología cartográfica.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [fincaId]);

  const dates = useMemo(
    () =>
      Array.from(
        new Set((data?.timeline ?? []).map((entry) => entry.captured_at)),
      ).sort(),
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
        <div className="font-medium">Visor cronológico v1</div>
        <p className="mt-1 text-sm">
          El catálogo indica qué capas admite la plataforma. Una capa solo
          aparecerá en el mapa cuando exista una campaña real con procedencia
          registrada.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="card space-y-5">
          <div>
            <div className="eyebrow">Finca</div>
            <h2 className="mt-1 break-all">{fincaId ?? "Sin identificar"}</h2>
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
                {dates.length === 0 ? "Sin campañas registradas" : "Todas"}
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
              {(data?.available_layers ?? []).map((layer) => (
                <label
                  key={layer.layer_type}
                  className="flex items-start gap-3 text-sm"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selectedLayers.has(layer.layer_type)}
                    onChange={() => toggleLayer(layer.layer_type)}
                  />
                  <span>
                    <span className="font-medium">{layer.label}</span>
                    <span className="muted mt-0.5 block">
                      {layer.description}
                    </span>
                  </span>
                </label>
              ))}
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
                ? "Comparación preparada."
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
                  Cargando contrato cartográfico…
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
                    No hay campañas cartográficas registradas
                  </div>
                  <p className="muted mt-2">
                    No se muestran geometrías, índices ni recomendaciones
                    simuladas. Las capas aparecerán después de que una campaña
                    real sea incorporada mediante un ticket de datos aprobado.
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
