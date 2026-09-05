import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  GeoJSONSource,
  LngLatBounds,
  Map,
  NavigationControl,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import {
  SAMPLING_REJECTION_REASONS,
  createSamplingOutboxAction,
  distanceMeters,
  type DevicePosition,
  type GeoJSONMultiPolygon,
  type SamplingPlan,
  type SamplingPlanLocator,
  type SamplingPoint,
  type SamplingRejectionReason,
} from "@/features/samplingField";
import {
  cacheSamplingPlan,
  enqueueSamplingAction,
  getCachedSamplingPlan,
  listSamplingOutbox,
  refreshAndCacheSamplingPlan,
  syncSamplingOutbox,
  type SamplingSyncResult,
} from "@/features/samplingOffline";
import type { SamplingOutboxAction } from "@/features/samplingField";

setWorkerUrl(mapWorkerUrl);

type MapData = Parameters<GeoJSONSource["setData"]>[0];

type PlanSource = "server" | "offline";

const EMPTY_MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "dbi-field-background",
      type: "background",
      paint: { "background-color": "#dce8e2" },
    },
  ],
};

const REJECTION_LABELS: Record<SamplingRejectionReason, string> = {
  road: "Vía/camino",
  infrastructure: "Infraestructura",
  canal_or_drain: "Canal o drenaje",
  non_banana: "No corresponde a banano",
  missing_plant: "Planta ausente",
  inaccessible: "Inaccesible",
  unsafe: "Condición insegura",
  other: "Otro",
};

function boundsForGeometry(geometry: GeoJSONMultiPolygon) {
  const bounds = new LngLatBounds();
  for (const polygon of geometry.coordinates) {
    for (const ring of polygon) {
      for (const coordinate of ring) {
        bounds.extend([coordinate[0], coordinate[1]]);
      }
    }
  }
  return bounds;
}

function areaGeoJSON(plan: SamplingPlan) {
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { kind: "boundary" },
        geometry: plan.boundary,
      },
      ...(plan.exclusions
        ? [
            {
              type: "Feature" as const,
              properties: { kind: "exclusion" },
              geometry: plan.exclusions,
            },
          ]
        : []),
    ],
  };
}

function pointsGeoJSON(plan: SamplingPlan) {
  return {
    type: "FeatureCollection" as const,
    features: plan.points.map((point) => ({
      type: "Feature" as const,
      properties: {
        point_id: point.point_id,
        role: point.role,
        status: point.status,
        sequence: point.sequence,
      },
      geometry: {
        type: "Point" as const,
        coordinates: [point.planned_longitude, point.planned_latitude],
      },
    })),
  };
}

function deviceGeoJSON(position: DevicePosition | null) {
  return {
    type: "FeatureCollection" as const,
    features: position
      ? [
          {
            type: "Feature" as const,
            properties: { kind: "device" },
            geometry: {
              type: "Point" as const,
              coordinates: [position.longitude, position.latitude],
            },
          },
        ]
      : [],
  };
}

function pointLabel(point: SamplingPoint) {
  return `${point.role === "primary" ? "Principal" : "Reserva"} ${point.sequence}`;
}

function statusLabel(point: SamplingPoint) {
  switch (point.status) {
    case "validated":
      return "Validado";
    case "rejected":
      return "Rechazado";
    case "substituted":
      return "Sustituido";
    default:
      return "Planificado";
  }
}

function outboxStateLabel(action: SamplingOutboxAction) {
  switch (action.state) {
    case "syncing":
      return "Sincronizando";
    case "conflict":
      return "Conflicto";
    case "auth_required":
      return "Requiere sesión";
    case "failed":
      return "Falló";
    default:
      return "Pendiente";
  }
}

function serverFallbackAllowed(error: unknown) {
  return !axios.isAxiosError(error) || !error.response;
}

export default function SamplingFieldPage() {
  const { organizationRef, farmId, plotId, planId } = useParams<{
    organizationRef: string;
    farmId: string;
    plotId: string;
    planId: string;
  }>();

  const locator = useMemo<SamplingPlanLocator | null>(() => {
    if (!organizationRef || !farmId || !plotId || !planId) return null;
    return { organizationRef, farmId, plotId, planId };
  }, [organizationRef, farmId, plotId, planId]);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const mapClickAttachedRef = useRef(false);
  const fittedPlanRef = useRef<string | null>(null);

  const [mapReady, setMapReady] = useState(false);
  const [plan, setPlan] = useState<SamplingPlan | null>(null);
  const [planSource, setPlanSource] = useState<PlanSource | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);
  const [position, setPosition] = useState<DevicePosition | null>(null);
  const [gpsError, setGpsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [outbox, setOutbox] = useState<SamplingOutboxAction[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [rejectionReason, setRejectionReason] =
    useState<SamplingRejectionReason>("inaccessible");

  const refreshOutbox = useCallback(async () => {
    if (!locator) {
      setOutbox([]);
      return;
    }
    setOutbox(await listSamplingOutbox(locator));
  }, [locator]);

  const loadPlan = useCallback(async () => {
    if (!locator) {
      setLoading(false);
      setError("La ruta de campo no contiene todos los identificadores requeridos.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      if (navigator.onLine) {
        try {
          const serverPlan = await refreshAndCacheSamplingPlan(locator);
          setPlan(serverPlan);
          setPlanSource("server");
          setSelectedPointId((current) =>
            serverPlan.points.some((point) => point.point_id === current)
              ? current
              : serverPlan.points.find(
                    (point) => point.role === "primary" && point.status === "planned",
                  )?.point_id ?? serverPlan.points[0]?.point_id ?? null,
          );
          return;
        } catch (requestError) {
          if (!serverFallbackAllowed(requestError)) throw requestError;
        }
      }

      const cached = await getCachedSamplingPlan(locator);
      if (!cached) {
        throw new Error(
          "No existe una copia offline de este plan. Ábralo al menos una vez con conexión.",
        );
      }
      setPlan(cached.plan);
      setPlanSource("offline");
      setSelectedPointId((current) =>
        cached.plan.points.some((point) => point.point_id === current)
          ? current
          : cached.plan.points.find(
                (point) => point.role === "primary" && point.status === "planned",
              )?.point_id ?? cached.plan.points[0]?.point_id ?? null,
      );
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null;
      setError(
        typeof detail === "string"
          ? detail
          : requestError instanceof Error
            ? requestError.message
            : "No se pudo abrir el plan Sampling.",
      );
    } finally {
      setLoading(false);
    }
  }, [locator]);

  const runSync = useCallback(async () => {
    if (!locator || !navigator.onLine || syncing) return;
    setSyncing(true);
    setSyncMessage(null);
    try {
      const result: SamplingSyncResult = await syncSamplingOutbox(locator);
      await refreshOutbox();
      if (result.synced > 0) {
        const serverPlan = await refreshAndCacheSamplingPlan(locator);
        setPlan(serverPlan);
        setPlanSource("server");
      }
      if (result.blockedState === "conflict") {
        setSyncMessage("Sincronización detenida por conflicto; revise la cola antes de continuar.");
      } else if (result.blockedState === "auth_required") {
        setSyncMessage("La cola requiere una sesión autorizada antes de continuar.");
      } else if (result.blockedState === "pending") {
        setSyncMessage("La red volvió a fallar; las acciones siguen pendientes.");
      } else if (result.blockedState === "failed") {
        setSyncMessage("Una acción falló y quedó conservada para revisión/reintento.");
      } else if (result.synced > 0) {
        setSyncMessage(`Se sincronizaron ${result.synced} acciones.`);
      }
    } catch (syncError) {
      setSyncMessage(
        syncError instanceof Error
          ? syncError.message
          : "No se pudo sincronizar la cola local.",
      );
    } finally {
      setSyncing(false);
    }
  }, [locator, refreshOutbox, syncing]);

  useEffect(() => {
    const online = () => setIsOnline(true);
    const offline = () => setIsOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  useEffect(() => {
    void loadPlan();
    void refreshOutbox();
  }, [loadPlan, refreshOutbox]);

  useEffect(() => {
    if (isOnline) void runSync();
  }, [isOnline, runSync]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    const map = new Map({
      container: mapContainerRef.current,
      style: EMPTY_MAP_STYLE,
      center: [-79.8, -3.3],
      zoom: 14,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: true }), "top-right");
    map.on("load", () => setMapReady(true));
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      mapClickAttachedRef.current = false;
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !plan) return;

    const area = areaGeoJSON(plan) as unknown as MapData;
    const points = pointsGeoJSON(plan) as unknown as MapData;

    const areaSource = map.getSource("sampling-area") as GeoJSONSource | undefined;
    if (areaSource) {
      areaSource.setData(area);
    } else {
      map.addSource("sampling-area", { type: "geojson", data: area });
      map.addLayer({
        id: "sampling-area-fill",
        type: "fill",
        source: "sampling-area",
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "kind"], "exclusion"],
            "#dc2626",
            "#0f766e",
          ],
          "fill-opacity": [
            "case",
            ["==", ["get", "kind"], "exclusion"],
            0.18,
            0.08,
          ],
        },
      });
      map.addLayer({
        id: "sampling-area-line",
        type: "line",
        source: "sampling-area",
        paint: {
          "line-color": [
            "case",
            ["==", ["get", "kind"], "exclusion"],
            "#b91c1c",
            "#0f766e",
          ],
          "line-width": 2,
        },
      });
    }

    const pointSource = map.getSource("sampling-points") as GeoJSONSource | undefined;
    if (pointSource) {
      pointSource.setData(points);
    } else {
      map.addSource("sampling-points", { type: "geojson", data: points });
      map.addLayer({
        id: "sampling-points",
        type: "circle",
        source: "sampling-points",
        paint: {
          "circle-radius": ["case", ["==", ["get", "role"], "reserve"], 6, 8],
          "circle-color": [
            "case",
            ["==", ["get", "status"], "validated"],
            "#16a34a",
            ["==", ["get", "status"], "rejected"],
            "#dc2626",
            ["==", ["get", "status"], "substituted"],
            "#d97706",
            ["==", ["get", "role"], "reserve"],
            "#2563eb",
            "#111827",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });
      map.addLayer({
        id: "sampling-selected",
        type: "circle",
        source: "sampling-points",
        filter: ["==", ["get", "point_id"], "__none__"],
        paint: {
          "circle-radius": 13,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": "#f59e0b",
          "circle-stroke-width": 3,
        },
      });
    }

    if (!map.getSource("sampling-device")) {
      map.addSource("sampling-device", {
        type: "geojson",
        data: deviceGeoJSON(position) as unknown as MapData,
      });
      map.addLayer({
        id: "sampling-device",
        type: "circle",
        source: "sampling-device",
        paint: {
          "circle-radius": 7,
          "circle-color": "#0ea5e9",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 3,
        },
      });
    }

    if (!mapClickAttachedRef.current) {
      map.on("click", "sampling-points", (event) => {
        const pointIdValue = event.features?.[0]?.properties?.point_id;
        if (typeof pointIdValue === "string") setSelectedPointId(pointIdValue);
      });
      mapClickAttachedRef.current = true;
    }

    if (fittedPlanRef.current !== plan.plan_id) {
      const bounds = boundsForGeometry(plan.boundary);
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 36, duration: 0 });
      }
      fittedPlanRef.current = plan.plan_id;
    }
  }, [mapReady, plan, position]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const source = map.getSource("sampling-device") as GeoJSONSource | undefined;
    source?.setData(deviceGeoJSON(position) as unknown as MapData);
  }, [mapReady, position]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.getLayer("sampling-selected")) return;
    map.setFilter("sampling-selected", [
      "==",
      ["get", "point_id"],
      selectedPointId ?? "__none__",
    ]);
  }, [mapReady, selectedPointId]);

  const selectedPoint = useMemo(
    () => plan?.points.find((point) => point.point_id === selectedPointId) ?? null,
    [plan, selectedPointId],
  );

  const reserveCandidate = useMemo(() => {
    if (!plan || !selectedPoint || selectedPoint.role !== "primary") return null;
    return (
      plan.points.find(
        (point) =>
          point.role === "reserve" &&
          point.reserve_for_sequence === selectedPoint.sequence &&
          point.status === "planned",
      ) ?? null
    );
  }, [plan, selectedPoint]);

  const distanceToSelected = useMemo(() => {
    if (!position || !selectedPoint) return null;
    return distanceMeters(
      position.longitude,
      position.latitude,
      selectedPoint.planned_longitude,
      selectedPoint.planned_latitude,
    );
  }, [position, selectedPoint]);

  const pendingForSelected = useMemo(
    () => outbox.filter((action) => action.pointId === selectedPointId),
    [outbox, selectedPointId],
  );

  const capturePosition = () => {
    setGpsError(null);
    if (!navigator.geolocation) {
      setGpsError("Este dispositivo/navegador no expone Geolocation API.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (gps) => {
        const nextPosition: DevicePosition = {
          longitude: Number(gps.coords.longitude.toFixed(7)),
          latitude: Number(gps.coords.latitude.toFixed(7)),
          accuracyM: Number(gps.coords.accuracy.toFixed(1)),
          capturedAt: new Date(gps.timestamp).toISOString(),
        };
        setPosition(nextPosition);
        mapRef.current?.flyTo({
          center: [nextPosition.longitude, nextPosition.latitude],
          zoom: Math.max(mapRef.current.getZoom(), 17),
        });
      },
      (gpsFailure) => {
        if (gpsFailure.code === gpsFailure.PERMISSION_DENIED) {
          setGpsError("Permiso GPS denegado. Habilite ubicación para navegar/validar.");
        } else if (gpsFailure.code === gpsFailure.TIMEOUT) {
          setGpsError("El GPS no respondió dentro del tiempo esperado.");
        } else {
          setGpsError("No fue posible obtener una posición GPS válida.");
        }
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15_000 },
    );
  };

  const queueAndMaybeSync = async (action: SamplingOutboxAction) => {
    await enqueueSamplingAction(action);
    await refreshOutbox();
    setSyncMessage("Acción guardada localmente.");
    if (navigator.onLine) await runSync();
  };

  const validateSelected = async () => {
    if (!locator || !selectedPoint || !position) return;
    await queueAndMaybeSync(
      createSamplingOutboxAction(locator, {
        kind: "validate",
        pointId: selectedPoint.point_id,
        payload: {
          longitude: position.longitude,
          latitude: position.latitude,
          observed_at: new Date().toISOString(),
        },
      }),
    );
  };

  const rejectSelected = async () => {
    if (!locator || !selectedPoint) return;
    await queueAndMaybeSync(
      createSamplingOutboxAction(locator, {
        kind: "reject",
        pointId: selectedPoint.point_id,
        payload: {
          rejection_reason: rejectionReason,
          observed_at: new Date().toISOString(),
        },
      }),
    );
  };

  const substituteSelected = async () => {
    if (!locator || !selectedPoint || !reserveCandidate || !position) return;
    await queueAndMaybeSync(
      createSamplingOutboxAction(locator, {
        kind: "substitute",
        pointId: selectedPoint.point_id,
        payload: {
          reserve_point_id: reserveCandidate.point_id,
          rejection_reason: rejectionReason,
          longitude: position.longitude,
          latitude: position.latitude,
          observed_at: new Date().toISOString(),
        },
      }),
    );
  };

  const focusPoint = (point: SamplingPoint) => {
    setSelectedPointId(point.point_id);
    mapRef.current?.flyTo({
      center: [point.planned_longitude, point.planned_latitude],
      zoom: Math.max(mapRef.current.getZoom(), 17),
    });
  };

  const primaryPoints = plan?.points.filter((point) => point.role === "primary") ?? [];
  const reservePoints = plan?.points.filter((point) => point.role === "reserve") ?? [];
  const conflicts = outbox.filter((action) => action.state === "conflict").length;

  return (
    <div className="space-y-4">
      <div
        className={`status-banner ${isOnline ? "status-banner-info" : "status-banner-warning"}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-medium">
              {isOnline ? "Con conexión" : "Modo offline"} · Sampling de campo
            </div>
            <p className="mt-1 text-sm">
              {planSource === "offline"
                ? "Mostrando el último snapshot local. La autoridad sigue siendo DBI server-side."
                : "El plan se obtuvo de DBI y su snapshot local está disponible para una pérdida de red posterior."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="chip">Pendientes: {outbox.length}</span>
            <span className="chip">Conflictos: {conflicts}</span>
            <button
              className="btn-secondary"
              disabled={!isOnline || syncing || outbox.length === 0}
              onClick={() => void runSync()}
            >
              {syncing ? "Sincronizando…" : "Sincronizar"}
            </button>
          </div>
        </div>
      </div>

      {syncMessage && <div className="status-banner text-sm">{syncMessage}</div>}
      {error && <div className="status-banner status-banner-danger">{error}</div>}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="card space-y-5">
          <div>
            <div className="eyebrow">Plan Sampling</div>
            <div className="mt-1 break-all text-sm font-medium">
              {plan?.plan_id ?? planId ?? "Sin plan"}
            </div>
            <div className="muted mt-2 text-sm">
              Estado: {plan?.status ?? (loading ? "cargando" : "no disponible")}
            </div>
            <div className="muted text-sm">
              {primaryPoints.length} principales · {reservePoints.length} reservas
            </div>
          </div>

          <div className="divider pt-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Ubicación del dispositivo</div>
                <div className="muted mt-1 text-xs">
                  El GPS se usa como evidencia de campo; nunca mueve el punto planificado ni una UP.
                </div>
              </div>
              <button className="btn-secondary" onClick={capturePosition}>
                Actualizar GPS
              </button>
            </div>
            {position && (
              <div className="mt-3 rounded-xl border p-3 text-xs">
                <div>{position.latitude.toFixed(7)}, {position.longitude.toFixed(7)}</div>
                <div className="muted mt-1">Precisión reportada: ±{position.accuracyM.toFixed(1)} m</div>
              </div>
            )}
            {gpsError && <div className="mt-3 text-sm text-rose-600">{gpsError}</div>}
          </div>

          <div className="divider pt-4">
            <div className="text-sm font-medium">Puntos principales</div>
            <div className="mt-3 max-h-[360px] space-y-2 overflow-auto pr-1">
              {primaryPoints.map((point) => (
                <button
                  key={point.point_id}
                  className={`w-full rounded-xl border p-3 text-left text-sm ${
                    point.point_id === selectedPointId ? "ring-2 ring-amber-400" : ""
                  }`}
                  onClick={() => focusPoint(point)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{pointLabel(point)}</span>
                    <span className="chip">{statusLabel(point)}</span>
                  </div>
                  <div className="muted mt-1 text-xs">
                    Ruta: {point.route_order ?? "—"}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <section className="card overflow-hidden p-0">
          <div className="relative min-h-[560px]">
            <div
              ref={mapContainerRef}
              className="absolute inset-0"
              aria-label="Mapa operativo offline de puntos Sampling"
            />
            {loading && (
              <div className="pointer-events-none absolute inset-x-4 bottom-4 status-banner bg-white/95 text-sm shadow-lg dark:bg-dal-petrol/95">
                Cargando plan Sampling…
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card space-y-4">
          <div>
            <div className="eyebrow">Punto seleccionado</div>
            <h2 className="mt-1">
              {selectedPoint ? pointLabel(selectedPoint) : "Seleccione un punto"}
            </h2>
          </div>

          {selectedPoint && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border p-3 text-sm">
                  <div className="muted text-xs">Estado DBI</div>
                  <div className="mt-1 font-medium">{statusLabel(selectedPoint)}</div>
                </div>
                <div className="rounded-xl border p-3 text-sm">
                  <div className="muted text-xs">Coordenada planificada</div>
                  <div className="mt-1 text-xs">
                    {selectedPoint.planned_latitude.toFixed(7)}, {selectedPoint.planned_longitude.toFixed(7)}
                  </div>
                </div>
                <div className="rounded-xl border p-3 text-sm">
                  <div className="muted text-xs">Distancia GPS</div>
                  <div className="mt-1 font-medium">
                    {distanceToSelected === null ? "Sin GPS" : `${distanceToSelected.toFixed(1)} m`}
                  </div>
                </div>
                <div className="rounded-xl border p-3 text-sm">
                  <div className="muted text-xs">Cola local para este punto</div>
                  <div className="mt-1 font-medium">{pendingForSelected.length}</div>
                </div>
              </div>

              {selectedPoint.role === "primary" && selectedPoint.status === "planned" ? (
                <div className="divider space-y-4 pt-4">
                  <div>
                    <label className="text-sm font-medium" htmlFor="sampling-rejection-reason">
                      Motivo para rechazo/sustitución
                    </label>
                    <select
                      id="sampling-rejection-reason"
                      className="mt-2 w-full max-w-md"
                      value={rejectionReason}
                      onChange={(event) =>
                        setRejectionReason(event.target.value as SamplingRejectionReason)
                      }
                    >
                      {SAMPLING_REJECTION_REASONS.map((reason) => (
                        <option key={reason} value={reason}>
                          {REJECTION_LABELS[reason]}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      className="btn-primary"
                      disabled={!position || pendingForSelected.length > 0}
                      onClick={() => void validateSelected()}
                    >
                      Validar en posición GPS
                    </button>
                    <button
                      className="btn-secondary"
                      disabled={pendingForSelected.length > 0}
                      onClick={() => void rejectSelected()}
                    >
                      Rechazar punto
                    </button>
                    <button
                      className="btn-secondary"
                      disabled={!position || !reserveCandidate || pendingForSelected.length > 0}
                      onClick={() => void substituteSelected()}
                    >
                      Sustituir por reserva
                    </button>
                  </div>

                  <p className="muted text-xs">
                    `reject` conserva motivo + fecha/hora según el contrato Sampling actual; no se presenta una coordenada de rechazo como dato persistido porque ese contrato todavía no la admite.
                  </p>
                  {reserveCandidate && (
                    <p className="muted text-xs">
                      Reserva asociada disponible: {pointLabel(reserveCandidate)}.
                    </p>
                  )}
                </div>
              ) : (
                <div className="status-banner text-sm">
                  Las acciones de decisión se habilitan únicamente para un principal todavía planificado. Las reservas se validan mediante una sustitución explícita.
                </div>
              )}
            </>
          )}
        </section>

        <aside className="card">
          <div className="eyebrow">Cola offline</div>
          <div className="mt-1 text-sm font-medium">{outbox.length} acciones locales</div>
          <div className="mt-4 max-h-[340px] space-y-2 overflow-auto">
            {outbox.length === 0 && (
              <div className="muted text-sm">No hay acciones pendientes.</div>
            )}
            {outbox.map((action) => (
              <div key={action.actionId} className="rounded-xl border p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{action.kind}</span>
                  <span className="chip">{outboxStateLabel(action)}</span>
                </div>
                <div className="muted mt-1 break-all">Punto: {action.pointId}</div>
                {action.lastError && (
                  <div className="mt-2 text-amber-700 dark:text-amber-200">
                    {action.lastError}
                  </div>
                )}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
