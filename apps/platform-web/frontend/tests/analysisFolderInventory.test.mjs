import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { INDEX_REFS, inventoryFolder } from "../src/features/analysisFolderInventory.ts";

const file = (root, name, size = 1024) => ({
  name,
  size,
  webkitRelativePath: `${root}/${name}`,
});
const multispectral = INDEX_REFS.flatMap(index => [
  file("MULTI", `${index.toUpperCase()}.cog.tif`),
  file("MULTI", `${index.toUpperCase()}_DIAGNOSTICO.qml`),
]);

test("six pairs of scientific TIFF/QML are inventoried, not certified or published", () => {
  const inventory = inventoryFolder("multispectral", multispectral);
  assert.equal(inventory.rootName, "MULTI");
  assert.equal(inventory.totalFiles, 12);
  assert.equal(inventory.candidateCount, 12);
  assert.deepEqual(inventory.missing, []);
  assert.deepEqual(inventory.issues, []);
  assert.equal(inventory.scientificValidated, false);
  assert.equal(inventory.uploaded, false);
  assert.equal(inventory.published, false);
  assert.equal(new Set(inventory.entries.map(x => x.role)).size, 12);
});

test("NDVI and GNDVI remain independent, QML historical name is recognized", () => {
  const inventory = inventoryFolder("multispectral", [
    file("SPECTRAL", "NDVI_DIAGNOSTICO_2_98.qml"),
    file("SPECTRAL", "GNDVI.cog.tiff"),
    file("SPECTRAL", "NDRE.cog.tif"),
  ]);
  assert.equal(inventory.entries[0].role, "ndvi · estilo QML");
  assert.equal(inventory.entries[1].role, "gndvi · ráster científico");
  assert.equal(inventory.entries[2].role, "ndre · ráster científico");
  assert.ok(inventory.missing.includes("NDVI · COG"));
  assert.ok(inventory.missing.includes("GNDVI · QML"));
  assert.ok(inventory.missing.includes("NDRE · QML"));
});

test("nesting can identify an unnamed TIFF, but ambiguous identity fails closed", () => {
  const entries = [
    { name: "raster.tif", size: 1500, webkitRelativePath: "MULTI/NDVI/raster.tif" },
    { name: "ambiguous.tif", size: 2000, webkitRelativePath: "MULTI/NDVI/NDRE/ambiguous.tif" },
    file("MULTI", "NDVI_NDRE.qml"),
  ];
  const result = inventoryFolder("multispectral", entries);
  assert.equal(result.entries[0].role, "ndvi · ráster científico");
  assert.equal(result.entries[1].role, "Índice ambiguo");
  assert.equal(result.entries[2].role, "Índice ambiguo");
  assert.ok(result.issues.some(x => x.includes("índice inequívoco")));
  assert.ok(result.missing.includes("NDVI · QML"));
});

test("duplicates, split folder roots and malformed relative paths are flagged", () => {
  const duplicates = inventoryFolder("multispectral", [
    file("MULTI", "NDVI.tif"), file("MULTI", "ndvi-copia.tif"),
    file("OTHER", "NDVI.qml"),
    { name: "orphan.tif", size: 10, webkitRelativePath: "" },
  ]);
  assert.ok(duplicates.issues.some(x => x.includes("2 archivos candidatos")));
  assert.ok(duplicates.issues.some(x => x.includes("más de una carpeta raíz")));
  assert.ok(duplicates.issues.some(x => x.includes("ruta relativa")));
  const same = inventoryFolder("geospatial", [file("GIS", "capa.gpkg"), file("GIS", "CAPA.GPKG")]);
  assert.ok(same.issues.some(x => x.includes("rutas duplicadas")));
});

test("geospatial recognizes candidates but does not decide GIS semantic role from extension", () => {
  const inventory = inventoryFolder("geospatial", [
    file("GEO", "ORTHOMOSAIC_RGB.tif"),
    file("GEO", "density.gpkg"),
    file("GEO", "plants.geojson"),
    file("GEO", "informe.pdf"),
    file("GEO", "scientific.tif"),
    file("GEO", "private.exe"),
  ]);
  assert.equal(inventory.candidateCount, 1);
  assert.equal(inventory.reviewCount, 4);
  assert.equal(inventory.excludedCount, 1);
  assert.ok(inventory.entries.some(x => x.role === "GeoPackage" && x.status === "review"));
  assert.ok(inventory.entries.some(x => x.role === "Ráster sin tipo confirmado" && x.status === "review"));
  assert.equal(inventory.uploaded, false);
});

test("oversized selections and empty folders cannot be mistaken for validated data", () => {
  const tooMany = Array.from({ length: 1501 }, (_, i) => file("GEO", `other_${i}.xml`));
  const inventory = inventoryFolder("geospatial", tooMany);
  assert.ok(inventory.issues.some(x => x.includes("1500")));
  assert.equal(inventory.entries.length, 1500);
  const empty = inventoryFolder("multispectral", []);
  assert.equal(empty.rootName, null);
  assert.equal(empty.missing.length, 12);
  assert.ok(empty.issues.length > 0);
});

test("two directory inputs are private and no upload or publication actions were added", () => {
  const view = readFileSync(new URL("../src/components/AdminAnalysisFolderPanel.tsx", import.meta.url), "utf8");
  const page = readFileSync(new URL("../src/pages/FarmMapTimeline.tsx", import.meta.url), "utf8");
  assert.match(view, /webkitdirectory/);
  assert.match(view, /directoryPicker/);
  assert.match(view, /selectFolder\("geospatial"/);
  assert.match(view, /selectFolder\("multispectral"/);
  assert.doesNotMatch(view, /api\.(get|post|put)|fetch\(|arrayBuffer\(|FileReader|publishGeoJSON/);
  assert.match(page, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(page, /<AdminAnalysisFolderPanel key=\{gisScopeKey\} \/>/);
});
