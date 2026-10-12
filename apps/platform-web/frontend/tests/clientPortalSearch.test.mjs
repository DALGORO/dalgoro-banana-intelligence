import test from "node:test";
import assert from "node:assert/strict";
import { filterClientPortalFarms } from "../src/features/clientPortalSearch.ts";

const accounts = [
  {
    tenant_ref: "tenant-authorized-a",
    farms: [
      {
        id: "farm-a", organization_ref: "org-a", name: "Finca El Paraíso",
        code: "F-01",
        plots: [
          { id: "plot-a1", code: "L-01", name: "Lote Río", area_hectares: 2 },
          { id: "plot-a2", code: "L-02", name: "Lote Norte", area_hectares: null },
        ],
      },
      { id: "farm-empty", organization_ref: "org-a", name: "Finca Sin Lotes",
        code: "F-02", plots: [] },
    ],
  },
  {
    tenant_ref: "tenant-authorized-b",
    farms: [{
      id: "farm-b", organization_ref: "org-b", name: "Estación Agrícola",
      code: "F-03", plots: [
        { id: "plot-b1", code: "L-01", name: "Lote Sur", area_hectares: 9 },
      ],
    }],
  },
];

test("without search, all authorized farms, including empty farms, are preserved", () => {
  const result = filterClientPortalFarms(accounts, " ");
  assert.equal(result.length, 3);
  assert.deepEqual(result.map(x => x.account), [
    "tenant-authorized-a", "tenant-authorized-a", "tenant-authorized-b",
  ]);
  assert.deepEqual(result.map(x => x.visiblePlots.length), [2, 0, 1]);
});

test("searching a farm includes all its authorized plots, even with accents", () => {
  const matches = filterClientPortalFarms(accounts, " paraIso ");
  assert.equal(matches.length, 1);
  assert.equal(matches[0].farm.id, "farm-a");
  assert.deepEqual(matches[0].visiblePlots.map(x => x.id), ["plot-a1", "plot-a2"]);
});

test("searching a plot limits visible plots instead of returning entire farm", () => {
  const result = filterClientPortalFarms(accounts, "río");
  assert.equal(result.length, 1);
  assert.equal(result[0].farm.id, "farm-a");
  assert.deepEqual(result[0].visiblePlots.map(p => p.id), ["plot-a1"]);
  assert.equal(result.reduce((sum, x) => sum + x.visiblePlots.length, 0), 1);
});

test("searching matching plot codes preserves each account/farm identity", () => {
  const result = filterClientPortalFarms(accounts, "l-01");
  assert.equal(result.length, 2);
  assert.deepEqual(result.map(x => x.account + ":" + x.farm.id + ":" + x.visiblePlots[0].id), [
    "tenant-authorized-a:farm-a:plot-a1",
    "tenant-authorized-b:farm-b:plot-b1",
  ]);
});

test("unmatched query has empty results and original authorized input is immutable", () => {
  assert.deepEqual(filterClientPortalFarms(accounts, "no such field"), []);
  assert.deepEqual(accounts[0].farms[0].plots.map(p => p.id), ["plot-a1", "plot-a2"]);
});

test("empty server-approved set never invents a farm or plot", () => {
  assert.deepEqual(filterClientPortalFarms([], "lote"), []);
});
