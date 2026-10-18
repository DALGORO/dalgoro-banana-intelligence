import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inventoryFolder } from "../src/features/analysisFolderInventory.ts";
import { MAX_PRIVATE_GIS_SIZE, MAX_PRIVATE_GIS_BATCH, planPrivateGISUpload } from "../src/features/privateGISUploadPlan.ts";

const file = (path, size = 1024) => ({
  webkitRelativePath: path, name: path.split("/").at(-1), size,
});
const plan = (files) => planPrivateGISUpload(inventoryFolder("geospatial", files), files);

test("two recognized originals are eligible for existing private GIS endpoint only", () => {
  const files = [
    file("CARPETA1/plantas.gpkg"),
    file("CARPETA1/datos/sectores.ZIP"),
    file("CARPETA1/ortofoto_RGB.tif"),
    file("CARPETA1/NDVI.cog.tif"),
    file("CARPETA1/reporte.pdf"),
    file("CARPETA1/boundaries.geojson"),
    file("CARPETA1/test.qml"),
  ];
  const result = plan(files);
  assert.equal(result.ready, true);
  assert.equal(result.candidates.length, 2);
  assert.deepEqual(result.candidates.map(x => x.kind), ["gpkg", "shp_zip"]);
  assert.deepEqual(result.candidates.map(x => x.path), ["CARPETA1/plantas.gpkg", "CARPETA1/datos/sectores.ZIP"]);
  assert.ok(!result.candidates.some(x => /ndvi|ortofoto|reporte|geojson|qml/i.test(x.path)));
});

test("invalid inventory, duplicate case-insensitive names, and ambiguous roots block ALL uploads", () => {
  let files = [file("CARPETA1/a.gpkg"), file("CARPETA1/dir/A.gpkg")];
  let result = plan(files);
  assert.equal(result.ready, false);
  assert.ok(result.blockers.some(x => x.includes("nombre duplicado")));
  files = [file("CARPETA1/a.gpkg"), file("CARPETA2/b.gpkg")];
  result = plan(files);
  assert.equal(result.ready, false);
  assert.equal(result.candidates.length, 0);
  files = [file("CARPETA1/a.gpkg"), file("CARPETA1/A.gpkg")];
  assert.equal(plan(files).ready, false);
  assert.equal(planPrivateGISUpload(null, files).ready, false);
});

test("size policy fail-closed for one invalid file in otherwise valid batch", () => {
  assert.equal(MAX_PRIVATE_GIS_SIZE, 30 * 1024 * 1024);
  assert.equal(MAX_PRIVATE_GIS_BATCH, 8);
  for (const size of [0, MAX_PRIVATE_GIS_SIZE + 1]) {
    const r = plan([file("GIS/healthy.gpkg", 1024), file("GIS/bad.zip", size)]);
    assert.equal(r.ready, false);
    assert.ok(r.blockers.some(x => x.includes("30 MiB")));
  }
  assert.equal(plan([file("GIS/max.GPKG", MAX_PRIVATE_GIS_SIZE)]).ready, true);
  assert.equal(plan([file("GIS/a.exe")]).ready, false);
});

test("up to eight sources pass; nine are blocked rather than partly uploaded", () => {
  const pass = Array.from({ length: 8 }, (_, i) => file(`GIS/${i}.gpkg`));
  assert.equal(plan(pass).ready, true);
  const fail = plan([...pass, file("GIS/8.zip")]);
  assert.equal(fail.ready, false);
  assert.ok(fail.blockers.some(x => x.includes("Máximo 8")));
});

test("folder intake remains MANAGEMENT-only and uses only existing private original API", () => {
  const panel = readFileSync(new URL("../src/components/AdminAnalysisFolderPanel.tsx", import.meta.url), "utf8");
  const page = readFileSync(new URL("../src/pages/FarmMapTimeline.tsx", import.meta.url), "utf8");
  const vectors = readFileSync(new URL("../src/features/portalVectors.ts", import.meta.url), "utf8");
  assert.match(page, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(page, /<AdminAnalysisFolderPanel[\s\S]*?locator=\{realLocator\}[\s\S]*?campaigns=\{uploadCampaignChoices\}/);
  assert.match(panel, /stageGISOriginal\([\s\S]*?locator, source, chosenCampaign, "other"/);
  assert.match(panel, /listGISImports\(locator\)/);
  assert.match(panel, /existingReceipts\.filter\(item => item\.campaign_id === chosenCampaign\)/);
  assert.match(panel, /onImportsRefreshed\(receipts\)/);
  assert.match(panel, /disabled=\{busy \|\| !campaignAllowed \|\| !uploadPlan\.ready \|\| remaining\.length === 0\}/);
  assert.match(panel, /campaigns\.filter\(c => c\.status !== "APPROVED" && c\.status !== "PUBLISHED"\)/);
  assert.match(vectors, /"\/gis-imports"/);
  assert.doesNotMatch(panel, /publishGeoJSON|publishReviewedGISImport|publishInstitutionally|fetch\(|FileReader|\.arrayBuffer\(/);
});
