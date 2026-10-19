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

test("layer guide describes only the exact selected Campaign and existing public map sources", () => {
  const guideStyles = readFileSync(new URL("../src/pages/farm-map-layer-guide.css", import.meta.url), "utf8");
  const start = map.indexOf('<details className="dbi-map-layer-guide">');
  const end = map.indexOf('role="group" aria-label="Acciones rápidas para capas GIS del mapa"');
  assert.ok(start > 0 && end > start);
  const guide = map.slice(start, end);
  assert.match(guide, /<summary>/);
  assert.match(guide, /selectedVisit && !loading && !error/);
  assert.match(guide, /selectedVisit\.hasRgb/);
  assert.match(guide, /displayEntries\.length > 0 && rgbOverlayVisible/);
  assert.match(guide, /visibleVectorMeta\.length > 0/);
  assert.match(guide, /visibleVectorMeta\.filter\(layer => selectedVectorIds\.has\(layer\.id\)\)/);
  assert.match(guide, /campaignLoadError/);
  assert.match(guide, /ambiguousMapDate/);
  assert.match(guide, /Los mapas temáticos individuales todavía no están habilitados/);
  assert.match(guide, /href="#dbi-multi-evidence" onClick=\{\(\) => setInfoTab\("multi"\)\}/);
  assert.match(guide, /Disponible o seleccionada no significa descargada, procesada ni aprobada científicamente/);
  assert.match(guideStyles, /\.dbi-map-layer-guide > summary \{[\s\S]*?min-height:\s*44px/);
  assert.match(guideStyles, /\.dbi-map-layer-guide > summary:focus-visible/);
  assert.match(guideStyles, /\.dark \.dbi-map-layer-guide/);
  assert.doesNotMatch(guide, /api\.post|publishGeoJSON|stageGISOriginal|issue_part_access|presigned|Math\.random/);
});

test("layer guide is scoped to real lot and keeps existing published GIS quick actions", () => {
  assert.match(map, /\{realLocator && \(\s*<details className="dbi-map-layer-guide">/);
  assert.match(map, /const selectedVisit = mapVisits\.find\(visit => visit\.campaignId === selectedMapCampaignId/);
  assert.match(map, /const visibleVectorMeta = useMemo\(\(\) =>\s*vectorLayers\.filter\(layer => activeCampaignIds\.has\(layer\.campaign_id\)\)/);
  assert.match(map, /const displayEntries = useMemo/);
  assert.match(map, /const managementActiveCampaignIds = useMemo/);
  assert.match(map, /Mostrar todas/);
  assert.match(map, /Ocultar capas/);
});
