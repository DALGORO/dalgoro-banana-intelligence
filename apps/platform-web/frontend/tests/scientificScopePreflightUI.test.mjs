import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const panel = readFileSync(new URL("../src/components/AdminAnalysisFolderPanel.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/features/scientificScopePreflightApi.ts", import.meta.url), "utf8");
const portal = readFileSync(new URL("../src/pages/FarmMapTimeline.tsx", import.meta.url), "utf8");

test("manager only sees server Campaign scope check once 13 candidates and a MULTI campaign are selected", () => {
  assert.match(portal, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(panel, /scientificDraft\.structural_ready && campaignAllowed/);
  assert.match(panel, /c\.analysis_type === "multispectral"/);
  assert.match(panel, /verifyScientificCampaignScope\(locator, chosenCampaign, scientificDraft\)/);
  assert.match(panel, /Comprobar campaña en servidor \(sin subir archivos\)/);
  assert.match(panel, /Campaña multiespectral vinculada al lote/);
  assert.match(panel, /verifiedDraftKey === draftKey/);
  assert.match(panel, /setVerifiedDraftKey\(null\)/);
});

test("only draft metadata reaches existing authenticated API, response never certifies science", () => {
  assert.match(api, /api\.post<ScientificScopePreflightResponse>\(address, draft/);
  assert.match(api, /encodeURIComponent\(locator\.organizationRef\)/);
  assert.match(api, /"campaigns", encodeURIComponent\(campaignId\)/);
  assert.match(api, /"scientific-intake", "scope-preflight"/);
  assert.match(api, /"X-DBI-Tenant": locator\.tenantRef/);
  assert.match(api, /data\.campaign_link_verified !== true/);
  for (const flag of ["file_content_verified", "hashes_verified", "scientific_validated",
    "server_received", "institutional_approved", "published"]) {
    assert.match(api, new RegExp(`data\\.${flag} !== false`));
  }
  assert.doesNotMatch(api, /FormData|arrayBuffer\(|FileReader|stageGISOriginal|publishReviewedGISImport/);
});

test("UI does not convert successful scope check into publication or scientific hashes", () => {
  assert.match(panel, /Los archivos aún no están validados ni subidos/);
  assert.match(panel, /JSON\.stringify\(scientificDraft/);
  assert.doesNotMatch(panel, /institutionalPublicationApproved\s*=\s*true|setPublished\(true\)/);
});
