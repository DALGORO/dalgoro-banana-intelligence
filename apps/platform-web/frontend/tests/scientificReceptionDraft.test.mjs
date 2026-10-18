import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { INDEX_REFS, inventoryFolder } from "../src/features/analysisFolderInventory.ts";
import { prepareScientificReceptionDraft } from "../src/features/scientificReceptionDraft.ts";

const locator = {
  tenantRef: "tenant-dbi-test", organizationRef: "org-dbi-test",
  farmId: "00000000-0000-4000-8000-000000000001",
  plotId: "00000000-0000-4000-8000-000000000002",
};
const campaign = "00000000-0000-4000-8000-000000000003";
function file(root, name, size = 128) {
  return { name, size, webkitRelativePath: `${root}/${name}` };
}
const goodGeo = [file("GEO", "ORTHO_RGB.cog.tif", 10000000), file("GEO", "plants.gpkg", 100000)];
const goodMulti = INDEX_REFS.flatMap(index => [
  file("MULTI", `${index.toUpperCase()}.cog.tif`, 1000000),
  file("MULTI", `${index.toUpperCase()}_ESTILO.qml`, 10000),
]);
function draft(geo = goodGeo, multi = goodMulti, campaignId = campaign) {
  return prepareScientificReceptionDraft(
    locator, campaignId,
    inventoryFolder("geospatial", geo),
    inventoryFolder("multispectral", multi),
    geo, multi,
  );
}

test("two valid folder inventories produce precisely 1 RGB + 6 COG + 6 QML local references", () => {
  const result = draft();
  assert.equal(result.schema_version, "dbi-h14-scientific-reception-draft.v1");
  assert.equal(result.structural_ready, true);
  assert.deepEqual(result.blockers, []);
  assert.equal(result.files.length, 13);
  assert.equal(result.files.filter(f => f.role === "rgb").length, 1);
  assert.equal(result.files.filter(f => f.role === "scientific_cog").length, 6);
  assert.equal(result.files.filter(f => f.role === "qml_style").length, 6);
  assert.deepEqual(result.files.filter(f => f.role === "scientific_cog").map(f => f.index), [...INDEX_REFS]);
  assert.equal(result.scope.campaign_id, campaign);
  assert.equal(result.scope.tenant_ref, locator.tenantRef);
  assert.equal(result.files.find(f => f.role === "rgb").size_bytes, 10000000);
  assert.ok(result.files.every(f => f.size_bytes > 0 && f.sha256 === null && !f.file_content_verified));
  assert.deepEqual([result.scientific_validated, result.server_received, result.institutional_approved, result.published], [false, false, false, false]);
  assert.equal(result.state, "local_metadata_only_not_uploaded");
  assert.ok(!result.files.some(f => /\.gpkg/.test(f.relative_path)));
});

test("missing QML/COG, unknown RGB and an extra TIFF block the whole draft", () => {
  const noQml = draft(goodGeo, goodMulti.filter(f => !f.name.startsWith("NDRE_ESTILO")));
  assert.equal(noQml.structural_ready, false);
  assert.ok(noQml.blockers.some(b => b.includes("NDRE · QML")));
  const wrongRgb = draft([file("GEO", "image.tif")]);
  assert.equal(wrongRgb.structural_ready, false);
  assert.ok(wrongRgb.blockers.some(b => b.includes("Ortofoto RGB")));
  const extraRaster = draft([...goodGeo, file("GEO", "mystery.tif")]);
  assert.equal(extraRaster.structural_ready, false);
  assert.ok(extraRaster.blockers.some(b => b.includes("TIFF sin tipo confirmado")));
});

test("zero-byte source, duplicate scientific roles and conflicting file names are rejected", () => {
  const empty = draft(goodGeo, goodMulti.map(f => f.name === "NDVI.cog.tif" ? {...f, size: 0} : f));
  assert.equal(empty.structural_ready, false);
  assert.ok(empty.blockers.some(b => b.includes("archivo local ausente, vacío")));
  const duplicated = draft(goodGeo, [...goodMulti, file("MULTI", "NDVI_copy.tif")]);
  assert.equal(duplicated.structural_ready, false);
  assert.ok(duplicated.blockers.some(b => b.includes("exactamente un candidato")));
  const invalid = draft(goodGeo, [file("MULTI", "NDVI.cog.tif"), file("MULTI", "ndvi.COG.tif")]);
  assert.equal(invalid.structural_ready, false);
  assert.ok(invalid.blockers.length > 0);
});

test("bad campaign identity and mismatched metadata cannot produce a complete draft", () => {
  assert.equal(draft(goodGeo, goodMulti, "").structural_ready, false);
  assert.equal(draft(goodGeo, goodMulti, "anything").structural_ready, false);
  const mismatch = prepareScientificReceptionDraft(locator, campaign,
    inventoryFolder("geospatial", goodGeo), inventoryFolder("multispectral", goodMulti),
    [goodGeo[0]], goodMulti,
  );
  assert.equal(mismatch.structural_ready, false);
  assert.ok(mismatch.blockers.some(b => b.includes("no coincide con el inventario")));
});

test("UI exports only local unverified JSON when structurally complete and campaign selected", () => {
  const panel = readFileSync(new URL("../src/components/AdminAnalysisFolderPanel.tsx", import.meta.url), "utf8");
  const parent = readFileSync(new URL("../src/pages/FarmMapTimeline.tsx", import.meta.url), "utf8");
  assert.match(parent, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(panel, /prepareScientificReceptionDraft\(/);
  assert.match(panel, /scientificDraft\.structural_ready && campaignAllowed/);
  assert.match(panel, /JSON\.stringify\(scientificDraft/);
  assert.match(panel, /application\/json/);
  assert.match(panel, /Exportar borrador JSON local \(sin subir archivos\)/);
  assert.match(panel, /SHA-256/);
  assert.doesNotMatch(panel, /publishInstitutionally|publishGeoJSON|publishReviewedGISImport/);
});
