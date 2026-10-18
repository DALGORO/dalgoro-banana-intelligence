import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const map = readFileSync(new URL("../src/pages/FarmMapTimeline.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/components/dbi-client-view.css", import.meta.url), "utf8");

test("map-side quick actions only appear if published GIS metadata is available", () => {
  const section = map.slice(map.indexOf('<section id="dbi-map-view"'), map.indexOf('<section id="dbi-map-history"'));
  assert.match(section, /visibleVectorMeta\.length > 0 &&/);
  assert.match(section, /role="group" aria-label="Acciones rápidas para capas GIS del mapa"/);
  assert.match(section, /Capas GIS publicadas/);
  assert.match(section, /visibleVectorMeta\.filter\(layer => selectedVectorIds\.has\(layer\.id\)\)/);
  assert.match(section, /Mostrar todas/);
  assert.match(section, /Ocultar capas/);
  assert.match(section, /setVisibleGISLayers\(true\)/);
  assert.match(section, /setVisibleGISLayers\(false\)/);
  assert.match(section, /La fotografía RGB se controla por separado/);
  assert.doesNotMatch(section, /publishGeoJSON|stageGISOriginal|publishInstitutionally|fetch\(|api\.post/);
});

test("map-side buttons are touch-friendly on mobile and accessible by keyboard", () => {
  assert.match(css, /\.dbi-map-quick-tools/);
  assert.match(css, /\.dbi-map-quick-buttons button \{[\s\S]*?min-height: 44px/);
  assert.match(css, /\.dbi-map-quick-buttons button:focus-visible/);
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*?\.dbi-map-quick-buttons/);
});

test("existing per-campaign GIS scoping and published read remain unchanged", () => {
  assert.match(map, /const visibleVectorMeta = useMemo/);
  assert.match(map, /const setVisibleGISLayers = \(show: boolean\) =>/);
  assert.match(map, /for \(const layer of visibleVectorMeta\)/);
  assert.match(map, /const managementActiveCampaignIds = useMemo/);
  assert.match(map, /Los seis índices están calculados como estadísticas de muestras/);
});
