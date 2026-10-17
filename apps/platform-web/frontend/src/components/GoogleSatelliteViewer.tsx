import { useEffect, useRef, useState } from "react";
import {
  apiResourceUrl, mapLibreDbiHeaders, type RasterTileTimelineEntry,
} from "@/features/mapTimeline";
import type { VectorLayerDetail } from "@/features/portalVectors";
import { createGISFeatureDetails, GIS_KIND_COLORS } from "@/features/gisPresentation";

type Position = { lat: number; lng: number };
type TilePoint = { x: number; y: number };
type MapType = {
  tileSize: object;
  getTile: (coord: TilePoint, zoom: number, document: Document) => HTMLElement;
  releaseTile: (node: HTMLElement) => void;
};
type DbiRasterOverlay = MapType & {
  setOpacity: (opacity: number) => void;
  dispose: () => void;
};
type DataFeature = {
  setProperty: (key: string, value: string) => void;
  getProperty: (key: string) => unknown;
  forEachProperty: (callback: (value: unknown, key: string) => void) => void;
};
type DataMouseEvent = { feature: DataFeature; latLng: Position };
type MapsListener = { remove: () => void };
type InfoWindow = {
  setContent: (content: HTMLElement) => void;
  open: (options: { map: SatelliteMap; position: Position }) => void;
  close: () => void;
};
type SatelliteMap = {
  data: {
    addListener: (event: "click", handler: (event: DataMouseEvent) => void) => MapsListener;
    addGeoJson: (geojson: object) => DataFeature[];
    forEach: (callback: (feature: object) => void) => void;
    remove: (feature: object) => void;
    setStyle: (style: (feature: { getProperty: (name: string) => string }) => object) => void;
  };
  overlayMapTypes: { clear: () => void; push: (overlay: MapType) => void };
  fitBounds: (bounds: { west: number; south: number; east: number; north: number }) => void;
};
type GoogleSDK = {
  maps: {
    Map: new (container: HTMLElement, options: {
      center: Position; zoom: number; mapTypeId: string;
      tilt: number; mapTypeControl: boolean; zoomControl: boolean;
      streetViewControl: boolean;
    }) => SatelliteMap;
    Size: new (width: number, height: number) => object;
    InfoWindow: new (options: { maxWidth: number }) => InfoWindow;
  };
};

declare global {
  interface Window {
    google?: GoogleSDK;
    __dbiGoogleMapsReady?: () => void;
  }
}

const GOOGLE_MAPS_LOAD_TIMEOUT_MS = 18000;
let googleSDKPromise: Promise<GoogleSDK> | null = null;

function loadGoogleMaps(apiKey: string): Promise<GoogleSDK> {
  if (window.google?.maps) return Promise.resolve(window.google);
  if (googleSDKPromise) return googleSDKPromise;

  googleSDKPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    let completed = false;
    let timeout: number | null = null;

    const cleanUp = () => {
      if (timeout !== null) window.clearTimeout(timeout);
      delete window.__dbiGoogleMapsReady;
      script.onerror = null;
    };
    const fail = (message: string) => {
      if (completed) return;
      completed = true;
      cleanUp();
      script.remove();
      // No retener indefinidamente una Promise fallida: el productor podrá reintentar.
      googleSDKPromise = null;
      reject(new Error(message));
    };

    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly&loading=async&callback=__dbiGoogleMapsReady`;
    window.__dbiGoogleMapsReady = () => {
      if (!window.google?.maps) {
        fail("Google Satélite no pudo inicializarse.");
        return;
      }
      if (completed) return;
      completed = true;
      cleanUp();
      resolve(window.google);
    };
    script.onerror = () => fail("No se pudo conectar con Google Satélite.");
    timeout = window.setTimeout(
      () => fail("Google Satélite no respondió. Comprueba la conexión e inténtalo de nuevo."),
      GOOGLE_MAPS_LOAD_TIMEOUT_MS,
    );
    document.head.appendChild(script);
  });
  return googleSDKPromise;
}

function authorizedRasterOverlay(
  google: GoogleSDK,
  entry: RasterTileTimelineEntry,
  tenantRef: string,
  initialOpacity: number,
  onTileError: () => void,
): DbiRasterOverlay {
  const pending = new Map<HTMLElement, { abort: AbortController; url?: string }>();
  let opacity = initialOpacity;

  function release(node: HTMLElement) {
    const record = pending.get(node);
    record?.abort.abort();
    if (record?.url) URL.revokeObjectURL(record.url);
    pending.delete(node);
  }

  return {
    setOpacity(value) {
      opacity = value;
      // No volver a descargar mosaicos al mover el control de transparencia.
      for (const tile of pending.keys()) tile.style.opacity = String(opacity);
    },
    dispose() {
      for (const tile of pending.keys()) release(tile);
    },
    tileSize: new google.maps.Size(256, 256),
    getTile(coord, zoom, ownerDocument) {
      const container = ownerDocument.createElement("div");
      container.style.width = "256px";
      container.style.height = "256px";
      container.style.opacity = String(opacity);
      const max = 2 ** zoom;
      if (coord.y < 0 || coord.y >= max || !Number.isInteger(zoom)) return container;
      const x = ((coord.x % max) + max) % max;
      const path = entry.tile_url_template
        .replace("{z}", String(zoom))
        .replace("{x}", String(x))
        .replace("{y}", String(coord.y));
      const abort = new AbortController();
      const record: { abort: AbortController; url?: string } = { abort };
      pending.set(container, record);
      void fetch(apiResourceUrl(path), {
        method: "GET",
        headers: mapLibreDbiHeaders(tenantRef),
        signal: abort.signal,
        credentials: "same-origin",
      }).then(async (response) => {
        if (!response.ok) {
          // Un 404 puede ser normal fuera de la huella del vuelo.
          // Problemas de autorización o red deben ser visibles al usuario.
          if ([401, 403, 429].includes(response.status) || response.status >= 500) onTileError();
          return;
        }
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          onTileError();
          return;
        }
        const blob = await response.blob();
        if (abort.signal.aborted) return;
        record.url = URL.createObjectURL(blob);
        const image = ownerDocument.createElement("img");
        image.src = record.url;
        image.width = 256;
        image.height = 256;
        image.alt = "";
        image.style.width = "100%";
        image.style.height = "100%";
        container.appendChild(image);
      }).catch(() => {
        // Abortar tiles al mover el mapa es normal; otros errores sí requieren aviso.
        if (!abort.signal.aborted) onTileError();
      });
      return container;
    },
    releaseTile(node) {
      release(node);
    },
  };
}

export function GoogleSatelliteViewer({
  tenantRef, entries, bounds, vectors = [], rasterOpacity = 0.75,
}: {
  tenantRef: string;
  entries: RasterTileTimelineEntry[];
  bounds: [number, number, number, number] | null;
  vectors?: VectorLayerDetail[];
  /** 0 = solo Google Satélite; 1 = ortofoto RGB totalmente opaca. */
  rasterOpacity?: number;
}) {
  const elementRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<SatelliteMap | null>(null);
  const overlaysRef = useRef<DbiRasterOverlay[]>([]);
  const opacityRef = useRef(rasterOpacity);
  opacityRef.current = rasterOpacity;
  const infoWindowRef = useRef<InfoWindow | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tileError, setTileError] = useState(false);
  const [retryVersion, setRetryVersion] = useState(0);
  const [tileRetryVersion, setTileRetryVersion] = useState(0);
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim() ?? "";
  // Con RGB al 0 %, no solicitar mosaicos privados invisibles.
  // El fondo Google sigue montado y las capas vectoriales continúan visibles.
  const rgbVisible = rasterOpacity > 0;

  useEffect(() => {
    let active = true;
    if (!apiKey || !elementRef.current) return;
    loadGoogleMaps(apiKey)
      .then((google) => {
        if (!active || !elementRef.current) return;
        mapRef.current = new google.maps.Map(elementRef.current, {
          center: { lat: -3.3, lng: -79.8 },
          zoom: 7,
          mapTypeId: "satellite",
          tilt: 0,
          // Google Satélite siempre es el fondo, no permitir cambiar a carreteras.
          mapTypeControl: false,
          zoomControl: true,
          streetViewControl: false,
        });
        setError(null);
        setReady(true);
      })
      .catch((err: Error) => {
        if (active) {
          setReady(false);
          setError(err.message);
        }
      });
    return () => {
      active = false;
      mapRef.current?.overlayMapTypes.clear();
      for (const overlay of overlaysRef.current) overlay.dispose();
      overlaysRef.current = [];
      infoWindowRef.current?.close();
      infoWindowRef.current = null;
      mapRef.current = null;
    };
  }, [apiKey, retryVersion]);

  useEffect(() => {
    const map = mapRef.current;
    const google = window.google;
    if (!ready || !map || !google?.maps) return;
    map.overlayMapTypes.clear();
    for (const overlay of overlaysRef.current) overlay.dispose();
    const overlays = rgbVisible
      ? entries.map(entry => authorizedRasterOverlay(
          google, entry, tenantRef, opacityRef.current, () => setTileError(true),
        ))
      : [];
    overlaysRef.current = overlays;
    for (const overlay of overlays) map.overlayMapTypes.push(overlay);
    return () => {
      map.overlayMapTypes.clear();
      for (const overlay of overlays) overlay.dispose();
      if (overlaysRef.current === overlays) overlaysRef.current = [];
    };
  }, [entries, ready, tenantRef, rgbVisible, tileRetryVersion]);

  useEffect(() => {
    for (const overlay of overlaysRef.current) overlay.setOpacity(rasterOpacity);
  }, [rasterOpacity]);

  useEffect(() => { setTileError(false); }, [entries, tenantRef, rgbVisible]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.data.forEach((feature) => map.data.remove(feature));
    for (const vector of vectors) {
      for (const feature of map.data.addGeoJson(vector.geojson)) {
        feature.setProperty("__dbi_layer_kind", vector.layer.layer_kind);
        feature.setProperty("__dbi_layer_name", vector.layer.name);
      }
    }
    map.data.setStyle((feature) => {
      const kind = feature.getProperty("__dbi_layer_kind");
      const isBoundary = kind === "boundaries";
      const palette = GIS_KIND_COLORS;
      const color = typeof kind === "string" && kind in palette
        ? palette[kind as keyof typeof palette]
        : palette.other;
      return {
        fillColor: color,
        fillOpacity: isBoundary ? 0.06 : 0.23,
        strokeColor: color,
        strokeWeight: isBoundary ? 3 : 2,
        icon: {
          path: 0, scale: 5,
          fillColor: color, fillOpacity: 1,
          strokeColor: "#ffffff", strokeWeight: 1,
        },
      };
    });
    return () => { map.data.forEach(feature => map.data.remove(feature)); };
  }, [ready, vectors]);

  useEffect(() => {
    const map = mapRef.current;
    const google = window.google;
    if (!ready || !map || !google?.maps) return;
    const info = new google.maps.InfoWindow({ maxWidth: 320 });
    infoWindowRef.current = info;
    const listener = map.data.addListener("click", (event) => {
      const fields: Record<string, unknown> = {};
      event.feature.forEachProperty((value, key) => { fields[key] = value; });
      const label = typeof fields.__dbi_layer_name === "string"
        ? fields.__dbi_layer_name : "Resultado cartográfico";
      info.setContent(createGISFeatureDetails(document, label, fields));
      info.open({ map, position: event.latLng });
    });
    return () => {
      listener.remove();
      info.close();
      infoWindowRef.current = null;
    };
  }, [ready]);

  useEffect(() => {
    if (!ready || !mapRef.current || !bounds) return;
    const [west, south, east, north] = bounds;
    mapRef.current.fitBounds({ west, south, east, north });
  }, [bounds, ready]);

  return (
    <div className="absolute inset-0">
      <div ref={elementRef} className="absolute inset-0" aria-label="Mapa satelital de Google con capas agrícolas privadas" />
      {!ready && !error && (
        <div role="status" className="absolute left-4 right-4 top-4 rounded-xl bg-white/95 p-3 text-sm text-slate-700 shadow">
          Conectando con Google Satélite…
        </div>
      )}
      {error && (
        <div role="alert" className="absolute left-4 right-4 top-4 rounded-xl bg-white p-4 text-sm text-rose-700 shadow">
          <p>{error} El fondo no está disponible; no se utilizarán imágenes satelitales simuladas.</p>
          <button type="button" className="btn-secondary mt-2" onClick={() => {
            setError(null);
            setRetryVersion(value => value + 1);
          }}>Reintentar Google Satélite</button>
          <p className="mt-2 text-xs">Si persiste, revisa conexión, clave, facturación y dominios autorizados de Google Maps.</p>
        </div>
      )}
      {ready && tileError && rgbVisible && (
        <div role="status" className="absolute bottom-4 left-4 right-4 rounded-xl bg-white/95 p-3 text-sm text-amber-900 shadow">
          <p>Google Satélite sigue visible, pero algunos mosaicos de la ortofoto privada no se cargaron.</p>
          <button type="button" className="btn-secondary mt-2" onClick={() => {
            setTileError(false);
            setTileRetryVersion(value => value + 1);
          }}>Reintentar fotografía RGB</button>
        </div>
      )}
    </div>
  );
}
