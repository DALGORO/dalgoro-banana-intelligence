import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const viewer = readFileSync(fileURLToPath(
  new URL("../src/components/GoogleSatelliteViewer.tsx", import.meta.url),
), "utf8");

test("Google satellite remains the official base and preserves Google attribution", () => {
  assert.match(viewer, /mapTypeId: "satellite"/);
  assert.match(viewer, /mapTypeControl: false/);
  assert.match(viewer, /https:\/\/maps\.googleapis\.com\/maps\/api\/js/);
  assert.doesNotMatch(viewer, /earth\.google\.com\/tiles|khms|google\.com\/vt\?/);
  assert.doesNotMatch(viewer, /attributionControl: false|disableDefaultUI: true/);
});

test("Google SDK load never waits forever and can be retried without a stale promise", () => {
  assert.match(viewer, /const GOOGLE_MAPS_LOAD_TIMEOUT_MS = 18000/);
  assert.match(viewer, /window\.setTimeout\([\s\S]*?GOOGLE_MAPS_LOAD_TIMEOUT_MS/);
  assert.match(viewer, /googleSDKPromise = null;[\s\S]*?reject\(new Error\(message\)\)/);
  assert.match(viewer, /script\.remove\(\)/);
  assert.match(viewer, /delete window\.__dbiGoogleMapsReady/);
  assert.match(viewer, /setRetryVersion\(value => value \+ 1\)/);
  assert.match(viewer, /\}, \[apiKey, retryVersion\]\)/);
  assert.match(viewer, /Reintentar Google Satélite/);
});

test("RGB tile failure warns, keeps Google visible, and offers per-visit retry", () => {
  assert.match(viewer, /\[401, 403, 429\]\.includes\(response\.status\)/);
  assert.match(viewer, /response\.status >= 500/);
  assert.match(viewer, /if \(!abort\.signal\.aborted\) onTileError\(\)/);
  assert.match(viewer, /setTileRetryVersion\(value => value \+ 1\)/);
  assert.match(viewer, /Reintentar fotografía RGB/);
  assert.match(viewer, /\[entries, ready, tenantRef, rgbVisible, tileRetryVersion\]/);
  assert.match(viewer, /tileSize: new google\.maps\.Size\(256, 256\)/);
  assert.match(viewer, /URL\.revokeObjectURL/);
  assert.match(viewer, /if \(!response\.ok\)/);
  assert.match(viewer, /setTileError\(false\)/);
});

test("no private RGB tile is fetched at opacity 0 or replaced with a fake background", () => {
  assert.match(viewer, /const rgbVisible = rasterOpacity > 0/);
  assert.match(viewer, /const overlays = rgbVisible\s*\? entries\.map/);
  assert.match(viewer, /: \[\];/);
  assert.match(viewer, /no se utilizarán imágenes satelitales simuladas/);
  assert.doesNotMatch(viewer, /Math\.random\(|mockSatellite|fakeTiles/);
});
