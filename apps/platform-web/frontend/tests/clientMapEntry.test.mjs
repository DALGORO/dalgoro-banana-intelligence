import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/ClientPortal.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/components/dbi-client-view.css", import.meta.url), "utf8");

test("client starts with clear three steps, not a technical upload panel", () => {
  assert.match(source, /Tu mapa en tres pasos/);
  assert.match(source, /Busca tu finca/);
  assert.match(source, /Abre el mapa de un lote/);
  assert.match(source, /Elige un vuelo y consulta sus capas/);
  assert.match(source, /Solo verás mapas y resultados publicados para tu lote/);
  assert.doesNotMatch(source, /webkitdirectory|publicar al cliente|<input[^>]+type="file"/i);
});

test("plot map action remains an authorized link, never a guessed layer", () => {
  assert.match(source, /filterClientPortalFarms\(accounts, search\)/);
  assert.match(source, /visiblePlots\.map\(plot => \(/);
  assert.match(source, /to=\{mapLink\(account, farm, plot\)\}/);
  assert.match(source, /Abrir mapa <ChevronRight/);
  assert.match(source, /Solo capas con evidencia real/);
  assert.doesNotMatch(source, /invented|fakeLayer|sampleFarm/);
});

test("simple entry styles include a touch-size CTA and mobile stacking", () => {
  assert.match(styles, /\.dbi-portal-map-action \{/);
  assert.match(styles, /min-height:\s*44px/);
  assert.match(styles, /\.dbi-portal-first-steps/);
  assert.match(styles, /@media \(max-width: 640px\)[\s\S]*\.dbi-portal-steps/);
  assert.match(styles, /\.dbi-portal-plot-link:focus-visible/);
});
