import { useEffect, useRef, useState } from "react";
import {
  apiResourceUrl, mapLibreDbiHeaders, type RasterTileTimelineEntry,
} from "@/features/mapTimeline";

type Position = { lat: number; lng: number };
type TilePoint = { x: number; y: number };
type MapType = {
  tileSize: object;
  getTile: (coord: TilePoint, zoom: number, document: Document) => HTMLElement;
  releaseTile: (node: HTMLElement) => void;
};
type SatelliteMap = {
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
  };
};

declare global {
  interface Window {
    google?: GoogleSDK;
    __dbiGoogleMapsReady?: () => void;
  }
}

let googleSDKPromise: Promise<GoogleSDK> | null = null;

function loadGoogleMaps(apiKey: string): Promise<GoogleSDK> {
  if (window.google?.maps) return Promise.resolve(window.google);
  if (googleSDKPromise) return googleSDKPromise;
  googleSDKPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly&loading=async&callback=__dbiGoogleMapsReady`;
    window.__dbiGoogleMapsReady = () => {
      if (window.google?.maps) resolve(window.google);
      else reject(new Error("Google Maps no pudo inicializarse."));
      delete window.__dbiGoogleMapsReady;
    };
    script.onerror = () => {
      googleSDKPromise = null;
      delete window.__dbiGoogleMapsReady;
      reject(new Error("No se pudo cargar Google Maps."));
    };
    document.head.appendChild(script);
  });
  return googleSDKPromise;
}

function authorizedRasterOverlay(
  google: GoogleSDK,
  entry: RasterTileTimelineEntry,
  tenantRef: string,
): MapType {
  const pending = new WeakMap<HTMLElement, { abort: AbortController; url?: string }>();

  return {
    tileSize: new google.maps.Size(256, 256),
    getTile(coord, zoom, ownerDocument) {
      const container = ownerDocument.createElement("div");
      container.style.width = "256px";
      container.style.height = "256px";
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
        if (!response.ok || !response.headers.get("content-type")?.startsWith("image/png")) return;
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
        // Sin mosaico autorizado, permanece visible la base satelital de Google.
      });
      return container;
    },
    releaseTile(node) {
      const record = pending.get(node);
      record?.abort.abort();
      if (record?.url) URL.revokeObjectURL(record.url);
      pending.delete(node);
    },
  };
}

export function GoogleSatelliteViewer({
  tenantRef, entries, bounds,
}: {
  tenantRef: string;
  entries: RasterTileTimelineEntry[];
  bounds: [number, number, number, number] | null;
}) {
  const elementRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<SatelliteMap | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim() ?? "";

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
          mapTypeControl: true,
          zoomControl: true,
          streetViewControl: false,
        });
        setReady(true);
      })
      .catch((err: Error) => { if (active) setError(err.message); });
    return () => {
      active = false;
      mapRef.current?.overlayMapTypes.clear();
      mapRef.current = null;
    };
  }, [apiKey]);

  useEffect(() => {
    const map = mapRef.current;
    const google = window.google;
    if (!ready || !map || !google?.maps) return;
    map.overlayMapTypes.clear();
    for (const entry of entries) {
      map.overlayMapTypes.push(authorizedRasterOverlay(google, entry, tenantRef));
    }
    return () => { map.overlayMapTypes.clear(); };
  }, [entries, ready, tenantRef]);

  useEffect(() => {
    if (!ready || !mapRef.current || !bounds) return;
    const [west, south, east, north] = bounds;
    mapRef.current.fitBounds({ west, south, east, north });
  }, [bounds, ready]);

  return (
    <div className="absolute inset-0">
      <div ref={elementRef} className="absolute inset-0" aria-label="Mapa satelital de Google con capas agrícolas privadas" />
      {error && (
        <div role="alert" className="absolute left-4 right-4 top-4 rounded-xl bg-white p-4 text-sm text-rose-700 shadow">
          {error} Revisa la clave y las restricciones de Google Maps.
        </div>
      )}
    </div>
  );
}
