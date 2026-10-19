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

test("producer UX gives a keyboard-accessible jump to existing authorized farms", () => {
  assert.match(source, /href="#dbi-portal-farms"/);
  assert.match(source, /id="dbi-portal-farms"/);
  assert.match(source, /Explorar mis fincas/);
  assert.match(styles, /\.dbi-portal-hero-cta:focus-visible/);
  assert.match(styles, /\.dbi-portal-hero-cta[\s\S]*min-height:\s*44px/);
});

test("farm search and live result totals use only the same authorized filtered catalog", () => {
  assert.match(source, /label htmlFor="dbi-portal-search"/);
  assert.match(source, /id="dbi-portal-search"/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /\{farms\.length\}/);
  assert.match(source, /\{totalPlots\}/);
  assert.match(source, /filterClientPortalFarms\(accounts, search\)/);
  assert.match(source, /\{farm\.code\}/);
  assert.match(source, /\{plot\.code\}/);
  assert.doesNotMatch(source, /invented|fakeLayer|sampleFarm|grant|presigned/i);
});
