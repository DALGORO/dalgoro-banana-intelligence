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
