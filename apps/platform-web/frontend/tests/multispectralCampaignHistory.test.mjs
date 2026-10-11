import test from "node:test";
import assert from "node:assert/strict";

import { verifiedMultispectralCampaigns, extractionForMapCampaign } from "../src/features/multispectralCampaignHistory.ts";
import { belongsToSelectedMapCampaign, mapTimelineViewKey } from "../src/features/mapCampaignSelection.ts";

const scope = {
  tenantRef: "tenant-ci",
  organizationRef: "org-ci",
  farmId: "10000000-0000-4000-8000-000000000080",
  plotId: "20000000-0000-4000-8000-000000000080",
};
const id = (n) => `a0000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const campaign = (n) => `b0000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const item = ({
  index = 1, campaignId = campaign(1),
  captured = "2026-09-15T09:00:00Z",
  registered = "2026-09-16T15:00:00Z",
  linkage = "verified_job_chain",
  override = {},
} = {}) => ({
  extraction_id: id(index),
  created_at: registered,
  observed_at: "2026-09-12T11:00:00Z",
  campaign_id: campaignId,
  captured_at: captured,
  campaign_linkage: linkage,
  payload: {
    tenant_ref: scope.tenantRef,
    organization_ref: scope.organizationRef,
    farm_id: scope.farmId,
    plot_id: scope.plotId,
    evidence_kind: "derived",
    ...override,
  },
});

test("empty and unverified evidence never creates fictitious Campaign", () => {
  assert.deepEqual(verifiedMultispectralCampaigns([], scope), []);
  assert.deepEqual(verifiedMultispectralCampaigns([
    item({linkage: "unverified"}),
    item({campaignId: null, index: 2}),
    item({captured: null, index: 3}),
    item({captured: "2026-09-15", index: 4}),
    item({captured: "untrusted", index: 5}),
    item({campaignId: "not-a-uuid", index: 6}),
  ], scope), []);
});

test("scope isolation excludes other tenants, organizations, farms and plots", () => {
  for (const key of ["tenant_ref", "organization_ref", "farm_id", "plot_id"]) {
    const mixed = item({override: {[key]: "foreign"}});
    assert.deepEqual(verifiedMultispectralCampaigns([mixed], scope), [], key);
  }
});

test("verified history groups flights, sorts captured_at and selects latest extraction", () => {
  const entries = [
    item({index: 1, campaignId: campaign(1), captured: "2026-09-15T09:00:00Z",
      registered: "2026-09-16T09:00:00Z"}),
    item({index: 2, campaignId: campaign(2), captured: "2026-10-01T10:00:00-05:00"}),
    item({index: 3, campaignId: campaign(1), captured: "2026-09-15T04:00:00-05:00",
      registered: "2026-09-20T09:00:00Z"}),
    item({index: 3, campaignId: campaign(1), captured: "2026-09-15T09:00:00Z"}),
  ];
  const history = verifiedMultispectralCampaigns(entries, scope);
  assert.equal(history.length, 2);
  assert.equal(history[0].campaignId, campaign(2));
  assert.equal(history[0].capturedAt, "2026-10-01T15:00:00.000Z");
  assert.equal(history[1].campaignId, campaign(1));
  assert.equal(history[1].extractionCount, 2);
  assert.equal(history[1].latestExtractionId, id(3));
  assert.equal(history[1].capturedAt, "2026-09-15T09:00:00.000Z");
});

test("conflicting capture timestamps for the same Campaign are excluded entirely", () => {
  const entries = [
    item({index: 1, captured: "2026-09-15T09:00:00Z"}),
    item({index: 2, captured: "2026-09-16T09:00:00Z"}),
    item({index: 3, captured: "2026-09-15T09:00:00Z"}),
  ];
  assert.deepEqual(verifiedMultispectralCampaigns(entries, scope), []);
});

test("the history refuses to invent trends or compare index values", () => {
  const entries = verifiedMultispectralCampaigns([
    item({index: 1, campaignId: campaign(1)}),
    item({index: 2, campaignId: campaign(2)}),
  ], scope);
  assert.equal(entries.length, 2);
  for (const result of entries) {
    assert.deepEqual(Object.keys(result).sort(), [
      "campaignId", "capturedAt", "extractionCount", "latestExtractionId",
    ].sort());
    assert.equal("ndvi_delta" in result, false);
    assert.equal("comparable" in result, false);
  }
});

test("map selection by exact verified Campaign chooses only matching evidence", () => {
  const records = [
    item({index: 1, campaignId: campaign(1), captured: "2026-09-15T09:00:00Z"}),
    item({index: 2, campaignId: campaign(2), captured: "2026-09-15T04:00:00-05:00"}),
    item({index: 3, campaignId: campaign(3), captured: "2026-10-01T10:00:00Z"}),
  ];
  assert.equal(extractionForMapCampaign(records, scope, "2026-09-15T09:00:00Z", null, ""), null,
    "La fecha compartida no acredita una Campaign concreta");
  const selected = extractionForMapCampaign(
    records, scope, "2026-09-15T09:00:00+00:00", campaign(2), id(1),
  );
  assert.equal(selected?.extraction_id, id(2));
  assert.equal(extractionForMapCampaign(
    records, scope, "2026-09-15T09:00:00Z", campaign(3), "",
  ), null, "No ignorar discordancia entre ID Campaign y fecha");
  assert.equal(extractionForMapCampaign(
    records, scope, "2026-10-01T10:00:00Z", null, id(1),
  )?.extraction_id, id(3));
});

test("unverified and scope-crossing records never appear as map-linked evidence", () => {
  const verified = item({index: 1});
  const unverified = item({index: 2, linkage: "unverified"});
  const foreign = item({index: 3, override: {tenant_ref: "other-tenant"}});
  const rows = [unverified, foreign, verified];
  assert.equal(extractionForMapCampaign(
    rows, scope, "2026-09-15T09:00:00Z", null, id(2),
  )?.extraction_id, id(1));
  assert.equal(extractionForMapCampaign(
    rows, scope, "not-a-date", null, "",
  ), null);
  assert.equal(extractionForMapCampaign(
    [unverified, foreign], scope, "2026-09-15T09:00:00Z", null, "",
  ), null);
  assert.equal(extractionForMapCampaign(
    [foreign, verified], {...scope, plotId: "plot-other"}, "", null, "",
  ), null);
  assert.equal(extractionForMapCampaign(
    rows, scope, "", null, id(2),
  )?.extraction_id, id(2), "Una extracción no vinculada se consulta solo sin fecha de mapa");
});


test("map renders only the matching Campaign when two share the same instant", () => {
  const moment = "2026-09-15T09:00:00Z";
  const selected = campaign(2);
  assert.equal(belongsToSelectedMapCampaign(moment, campaign(1), moment, selected), false);
  assert.equal(belongsToSelectedMapCampaign(moment, selected, moment, selected), true);
  assert.equal(belongsToSelectedMapCampaign("2026-09-15T04:00:00-05:00", selected, moment, selected), true);
  assert.equal(belongsToSelectedMapCampaign("2026-09-16T09:00:00Z", selected, moment, selected), false);
  assert.equal(belongsToSelectedMapCampaign(moment, campaign(1), moment, null), true);
  assert.equal(belongsToSelectedMapCampaign(moment, campaign(1), "", null), true);
  assert.equal(belongsToSelectedMapCampaign(moment, campaign(1), "", selected), false);
});

test("map/MULTI synchronization never substitutes data from another flight", () => {
  const a = item({index: 1, campaignId: campaign(1)});
  const b = item({index: 2, campaignId: campaign(2)});
  assert.equal(extractionForMapCampaign(
    [a, b], scope, "2026-09-15T09:00:00Z", null, id(1),
  ), null, "Una fecha ambigua no autoriza seleccionar el elemento previo");
  const second = extractionForMapCampaign(
    [a, b], scope, "2026-09-15T09:00:00Z", campaign(2), id(1),
  );
  assert.equal(second?.extraction_id, id(2));
  assert.equal(belongsToSelectedMapCampaign(
    "2026-09-15T09:00:00Z", campaign(1), "2026-09-15T09:00:00Z", campaign(2),
  ), false);
  const noMapProduct = extractionForMapCampaign(
    [a, b], scope, "2026-09-20T09:00:00Z", null, "",
  );
  assert.equal(noMapProduct, null, "No se pueden presentar índices de una fecha anterior");
});

test("map viewport and MULTI get a new instance when agricultural scope changes", () => {
  const base = {
    tenantRef: scope.tenantRef,
    organizationRef: scope.organizationRef,
    farmId: scope.farmId,
    plotId: scope.plotId,
  };
  const initial = mapTimelineViewKey(base);
  assert.equal(mapTimelineViewKey({ ...base }), initial, "La misma ruta no remonta la vista");
  for (const field of ["tenantRef", "organizationRef", "farmId", "plotId"]) {
    assert.notEqual(mapTimelineViewKey({ ...base, [field]: "other" }), initial,
      "Cambio de " + field + " debe desmontar todo el mapa, capas GIS y panel MULTI");
  }
  assert.notEqual(mapTimelineViewKey({ ...base, fincaId: "legacy-route" }), initial,
    "No mezclar rutas de finca antiguas y rutas por lote");
  assert.notEqual(
    mapTimelineViewKey({ tenantRef: "", fincaId: "legacy-farm-1" }),
    mapTimelineViewKey({ tenantRef: "", fincaId: "legacy-farm-2" }),
    "La ruta legacy también aísla su mapa por finca",
  );
});
