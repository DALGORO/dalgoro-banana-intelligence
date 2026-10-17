import test from "node:test";
import assert from "node:assert/strict";
import { producerMapVisits, visitsAtDate } from "../src/features/producerMapVisits.ts";

const raster = (campaignId, capturedAt, professional_review_status = "pending") => ({
  campaign_id: campaignId, captured_at: capturedAt, layer_type: "rgb",
  title: `Levantamiento ${campaignId}`, professional_review_status,
});

test("history only contains exact authorized map sources, not empty technical campaigns", () => {
  const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const c = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const timestamp = "2026-09-12T11:00:00Z";
  const visits = producerMapVisits(
    [raster(a, timestamp, "approved")],
    [
      { id: a, captured_at: timestamp, name: "Vuelo A" },
      { id: b, captured_at: timestamp, name: "Vuelo B" },
      { id: c, captured_at: "2026-10-14T11:00:00Z", name: "Sin imagen" },
    ],
    [{ campaign_id: a, id: "gis-1" }, { campaign_id: b, id: "gis-2" }],
  );
  assert.equal(visits.length, 2);
  assert.equal(visits[0].campaignId, a);
  assert.equal(visits[0].hasRgb, true);
  assert.equal(visits[0].gisLayerCount, 1);
  assert.equal(visits[0].reviewStatus, "approved");
  assert.equal(visits[1].campaignId, b);
  assert.equal(visits[1].hasRgb, false);
  assert.equal(visits[1].reviewStatus, "not_reported");
  assert.deepEqual(visitsAtDate(visits, timestamp).map(row => row.campaignId), [a, b],
    "Dos Campaign en el mismo instante siguen siendo distintas");
});

test("chronology sorts real dates newest first and rejects inconsistent provenance", () => {
  const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const c = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const visits = producerMapVisits(
    [
      raster(a, "2026-07-12T12:00:00Z"),
      raster(b, "2026-10-12T12:00:00Z"),
      raster(b, "2026-10-13T12:00:00Z"),
      raster(b, "2026-10-12T12:00:00Z"),
    ],
    [{ id: c, captured_at: "2026-09-12T12:00:00Z", name: "Lote GIS" }],
    [{ campaign_id: c, id: "layer-c" }, { campaign_id: b, id: "layer-b" }],
  );
  assert.deepEqual(visits.map(row => row.campaignId), [c, a],
    "No se vuelve a admitir una Campaign RGB contradictoria");
  assert.deepEqual(visitsAtDate(visits, "fecha incorrecta"), []);
});
