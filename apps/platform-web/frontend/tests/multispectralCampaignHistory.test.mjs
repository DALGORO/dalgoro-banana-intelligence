import test from "node:test";
import assert from "node:assert/strict";

import { verifiedMultispectralCampaigns, extractionForMapCampaign } from "../src/features/multispectralCampaignHistory.ts";

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
