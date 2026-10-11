import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const file = (relative) => readFileSync(new URL(relative, import.meta.url), "utf8");
const shell = file("../src/components/AppShell.tsx");
const map = file("../src/pages/FarmMapTimeline.tsx");
const multi = file("../src/components/MultispectralEvidencePanel.tsx");
const styles = file("../src/components/dbi-client-view.css");

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
  assert.match(multi, /sin comparación temporal/);
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
