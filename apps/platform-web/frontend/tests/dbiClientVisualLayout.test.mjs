import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { coverageLabel, INDEX_EXPLANATIONS } from "../src/features/producerEvidenceReadout.ts";

const file = (relative) => readFileSync(new URL(relative, import.meta.url), "utf8");
const shell = file("../src/components/AppShell.tsx");
const map = file("../src/pages/FarmMapTimeline.tsx");
const multi = file("../src/components/MultispectralEvidencePanel.tsx");
const styles = file("../src/components/dbi-client-view.css");
const tracking = file("../src/components/FarmTrackingPanel.tsx");

test("approved DBI client visual shell reuses the existing DALGORO PNG brand", () => {
  assert.match(shell, /src="\/logo-white\.png"/);
  assert.match(shell, /isDbiClientView \? 'dbi-client-shell'/);
  assert.match(styles, /#152e32/);
  assert.match(styles, /#b57b50/);
  assert.match(styles, /\.dbi-client-shell \.app-sidebar/);
  assert.match(shell, /to="\/portal"/);
  assert.match(shell, /to="\/companies"/);
});

test("map and MULTI use responsive columns without moving scientific calculations", () => {
  assert.match(map, /className="dbi-visual-grid"/);
  assert.match(map, /className="card dbi-map-stage/);
  assert.match(map, /<MultispectralEvidencePanel[\s\S]+selectedMapCampaignId=\{selectedMapCampaignId\}/);
  assert.match(multi, /className="card dbi-multi-panel/);
  assert.match(styles, /@media \(min-width: 1120px\)/);
  assert.match(styles, /@media \(min-width: 1560px\)/);
  assert.match(styles, /@media \(max-width: 767px\)/);
});

test("client only sees real derived summary; management still requires publish access", () => {
  assert.match(multi, /payload\.summaries\.filter\(item => item\.variable_kind === "index"\)\.map/);
  assert.match(multi, /\{number\(item\.median\)\}/);
  assert.match(multi, /no se deben comparar directamente entre vuelos/);
  assert.match(multi, /verifiedMultispectralCampaigns\(items, locator\)/);
  assert.match(map, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(map, /{selectedMapCampaignId && \(/);
  assert.match(map, /Sin capas cartográficas para la Campaign MULTI seleccionada/);
});

test("mobile quick date and side date share Campaign reset, not an inferred flight", () => {
  assert.match(map, /const selectPrimaryMapDate = \(date: string\) => \{\s*setSelectedDate\(date\);\s*setSpecificMapCampaign\(null\);/);
  const actions = map.match(/onChange=\{\(event\) => selectPrimaryMapDate\(event\.target\.value\)\}/g) ?? [];
  assert.equal(actions.length, 2, "El selector rápido y el lateral usan la misma regla de Campaign");
  assert.match(map, /id="dbi-mobile-date"/);
  assert.match(map, /disabled=\{dates\.length === 0\}/);
  assert.match(map, /dates\.map\(date => \(/);
  assert.match(map, /aria-label="Accesos rápidos del visor"/);
  assert.match(map, /href="#dbi-map-view"/);
  assert.match(map, /href="#dbi-tab-tracking" onClick=\{\(\) => setInfoTab\("tracking"\)\}/);
  assert.match(map, /realLocator && <a href="#dbi-multi-evidence"/);
  assert.match(map, /id="dbi-map-view"/);
  assert.match(multi, /id="dbi-multi-evidence"/);
});

test("mobile controls are visibly accessible only at phone breakpoint", () => {
  assert.match(styles, /\.dbi-mobile-toolbar \{\s*display: none;/);
  assert.match(styles, /@media \(max-width: 767px\) \{\s*\.dbi-mobile-toolbar \{\s*display: grid;/);
  assert.match(styles, /\.dbi-mobile-toolbar select \{[\s\S]*?min-height: 44px;/);
  assert.match(styles, /\.dbi-mobile-shortcuts a:focus-visible/);
  assert.match(styles, /\.dbi-map-stage,[\s\S]*?\.dbi-multi-panel \{\s*scroll-margin-top: 16px;/);
});

test("producer sees factual readout, not an inferred health score", () => {
  assert.match(multi, /aria-label="Lectura rápida para el productor"/);
  assert.match(multi, /Fecha de vuelo no verificada/);
  assert.match(multi, /verifiedFlight && selected\.captured_at/);
  assert.match(multi, /payload\.support_mode === "copa_up"/);
  assert.match(multi, /no representa hectáreas ni porcentaje/);
  assert.match(multi, /coverageLabel\(item\)/);
  assert.match(multi, /INDEX_EXPLANATIONS\[item\.variable_ref\]/);
  assert.match(multi, /<details className="dbi-producer-details">/);
  assert.match(multi, /P10–P90 = intervalo/);
  assert.match(styles, /\.dbi-producer-facts/);
});

test("coverage only reports valid source pixel counts; no hectare or plant inference", () => {
  assert.match(coverageLabel({ selected_count: 100, valid_count: 80, valid_fraction: 0.8 }), /80 de 100 píxeles válidos \(80%\)/);
  assert.equal(coverageLabel({ selected_count: 0, valid_count: 0, valid_fraction: 0 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 2, valid_count: 3, valid_fraction: 1 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 5, valid_count: -1, valid_fraction: 0 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: Number.NaN, valid_count: 1, valid_fraction: 0.5 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 10, valid_count: 5, valid_fraction: Number.NaN }),
    "5 de 10 píxeles válidos");
  assert.equal(coverageLabel({ selected_count: 10, valid_count: 5, valid_fraction: 1.2 }),
    "5 de 10 píxeles válidos");
  assert.equal(Object.keys(INDEX_EXPLANATIONS).length, 6);
  for (const value of Object.values(INDEX_EXPLANATIONS)) {
    assert.ok(value.length > 20, "Debe haber explicación por índice");
    assert.doesNotMatch(value, /tratamiento recomendado|cultivo enfermo|cultivo sano/i);
  }
});

test("tracking is an accessible tab INSIDE map viewer and MULTI remains mounted", () => {
  assert.match(map, /useState<"multi" \| "tracking">\("multi"\)/);
  assert.match(map, /className="dbi-info-tabs"/);
  assert.match(map, /role="tablist" aria-label="Pestañas de información agrícola"/);
  assert.match(map, /role="tab"\s+id="dbi-tab-multi"/);
  assert.match(map, /role="tab"\s+id="dbi-tab-tracking"/);
  assert.match(map, /aria-selected=\{infoTab === "multi"\}/);
  assert.match(map, /aria-selected=\{infoTab === "tracking"\}/);
  assert.match(map, /event\.key !== "ArrowRight" && event\.key !== "ArrowLeft"/);
  assert.match(map, /id="dbi-panel-multi"[\s\S]*?hidden=\{infoTab !== "multi"\}/);
  assert.match(map, /id="dbi-panel-tracking"[\s\S]*?hidden=\{infoTab !== "tracking"\}/);
  assert.match(map, /<FarmTrackingPanel[\s\S]*?visibleMapEntries=\{visibleEntries\}/);
  assert.match(map, /<MultispectralEvidencePanel[\s\S]*?selectedMapCampaignId=\{selectedMapCampaignId\}/);
  assert.ok(map.indexOf('id="dbi-map-view"') < map.indexOf('className="dbi-info-tabs"'),
    "El mapa permanece fuera de las pestañas y no se desmonta");
  assert.match(styles, /\.dbi-info-tab-panel\[hidden\] \{\s*display: none !important;/);
  assert.match(styles, /\.dbi-info-tabs \{ grid-column: 1 \/ -1; \}/);
  assert.match(styles, /\.dbi-client-shell \.dbi-info-tabs \{ grid-column: 3; \}/);
});

test("tracking only describes authorized visible entries and GIS, not diagnoses", () => {
  assert.match(tracking, /import type \{ MapTimelineEntry \}/);
  assert.match(tracking, /import type \{ VectorLayerInfo \}/);
  assert.match(tracking, /visibleMapEntries: readonly MapTimelineEntry\[\]/);
  assert.match(tracking, /associatedGISLayers: readonly VectorLayerInfo\[\]/);
  assert.match(tracking, /visibleMapEntries\.filter\([\s\S]*?entry\.layer_type === "inspections"/);
  assert.match(tracking, /layer\.layer_kind === "observations"/);
  assert.match(tracking, /No hay registros cartográficos activados para esta selección/);
  assert.match(tracking, /no inspecciones individuales verificadas/);
  assert.match(tracking, /Sin Campaign exacta seleccionada/);
  assert.match(tracking, /onOpenEvidence/);
  assert.match(tracking, /role="status"/);
  assert.match(tracking, /role="alert"/);
  assert.doesNotMatch(tracking, /api\.get\(|fetch\(|localStorage|setInterval/);
});
