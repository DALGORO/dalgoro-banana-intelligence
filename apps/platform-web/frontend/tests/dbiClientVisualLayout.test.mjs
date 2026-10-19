import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { coverageLabel, INDEX_EXPLANATIONS, percentileIntervalLabel } from "../src/features/producerEvidenceReadout.ts";
import { isObservationUUID, inspectionVersionMatchesScope, observedNumberLabel } from "../src/features/inspectionEvidenceRead.ts";

const file = (relative) => readFileSync(new URL(relative, import.meta.url), "utf8");
const shell = file("../src/components/AppShell.tsx");
const map = file("../src/pages/FarmMapTimeline.tsx");
const multi = file("../src/components/MultispectralEvidencePanel.tsx");
const styles = file("../src/components/dbi-client-view.css");
const tracking = file("../src/components/FarmTrackingPanel.tsx");
const inspect = file("../src/components/InspectionObservationLookup.tsx");
const clientHome = file("../src/pages/ClientPortal.tsx");
const approvedInspect = file("../src/components/ApprovedInspectionCampaignPanel.tsx");

test("approved DBI client visual shell reuses the existing DALGORO PNG brand", () => {
  assert.match(shell, /src="\/logo-white\.png"/);
  assert.match(shell, /isDbiClientView \? 'dbi-client-shell'/);
  assert.match(styles, /#152e32/);
  assert.match(styles, /#b57b50/);
  assert.match(styles, /\.dbi-client-shell \.app-sidebar/);
  assert.match(shell, /to="\/portal"/);
  assert.match(shell, /to="\/companies"/);
});

test("map and MULTI use responsive columns without moving scientific calculations", () => {
  assert.match(map, /className="dbi-visual-grid"/);
  assert.match(map, /className="card dbi-map-stage/);
  assert.match(map, /<MultispectralEvidencePanel[\s\S]+selectedMapCampaignId=\{selectedMapCampaignId\}/);
  assert.match(multi, /className="card dbi-multi-panel/);
  assert.match(styles, /@media \(min-width: 1120px\)/);
  assert.match(styles, /@media \(min-width: 1360px\)/);
  assert.match(styles, /@media \(max-width: 767px\)/);
});

test("producer gets four functional navigation steps and scoped bulk GIS controls", () => {
  assert.match(map, /aria-label="Consultar el lote paso a paso"/);
  assert.match(map, /href="#dbi-map-history"/);
  assert.match(map, /href="#dbi-map-controls"/);
  assert.match(map, /href="#dbi-tab-multi" onClick=\{\(\) => setInfoTab\("multi"\)\}/);
  assert.match(map, /href="#dbi-tab-tracking" onClick=\{\(\) => setInfoTab\("tracking"\)\}/);
  assert.match(map, /Consultar informe PDF/);
  assert.match(map, /const setVisibleGISLayers = \(show: boolean\) =>/);
  const bulk = map.slice(map.indexOf("const setVisibleGISLayers"), map.indexOf("const toggleLayer", map.indexOf("const setVisibleGISLayers")));
  assert.match(bulk, /for \(const layer of visibleVectorMeta\)/);
  assert.match(bulk, /if \(show\) next\.add\(layer\.id\)/);
  assert.match(bulk, /else next\.delete\(layer\.id\)/);
  assert.doesNotMatch(bulk, /vectorLayers\.map|managementCampaigns/);
  assert.match(map, /role="group" aria-label="Visibilidad de capas GIS publicadas"/);
  assert.match(map, /disabled=\{visibleVectorMeta\.every\(layer => selectedVectorIds\.has\(layer\.id\)\)\}/);
  assert.match(map, /disabled=\{visibleVectorMeta\.every\(layer => !selectedVectorIds\.has\(layer\.id\)\)\}/);
  assert.match(styles, /\.dbi-producer-guide-steps/);
  assert.match(styles, /\.dbi-gis-visibility-actions button:focus-visible/);
});

test("client only sees real derived summary; management still requires publish access", () => {
  assert.match(multi, /Object\.entries\(INDEX_LABELS\)\.filter\(\(\[ref\]\) => visibleIndices\.has\(ref\)\)/);
  assert.match(multi, /item \? number\(item\.median\) : "No disponible"/);
  assert.match(multi, /no se deben comparar directamente entre vuelos/);
  assert.match(multi, /verifiedMultispectralCampaigns\(items, locator\)/);
  assert.match(map, /\{canPublish && realLocator && \(\s*<details/);
  assert.match(map, /{selectedMapCampaignId && \(/);
  assert.match(map, /Este levantamiento no tiene capas cartográficas disponibles/);
});

test("scoped map preserves user date when asynchronous RGB response returns", () => {
  const responseStart = map.indexOf(".then((response) => {");
  const responseEnd = map.indexOf(".catch((requestError)", responseStart);
  assert.ok(responseStart > 0 && responseEnd > responseStart);
  const section = map.slice(responseStart, responseEnd);
  assert.match(section, /if \(!realLocator && !manuallySelectedVisitRef\.current\) \{/);
  assert.match(section, /setSelectedDate\(dates\.at\(-1\) \?\? ""\)/);
  assert.ok(!section.includes("setComparisonDate("), "Una respuesta tardía no resetea la comparación manual");

  const privateRead = map.indexOf("listGISImports(realLocator)");
  const privateEffectStart = map.lastIndexOf("  useEffect(() => {", privateRead);
  const privateEffectEnd = map.indexOf("  }, [realLocator, gisScopeKey, canPublish]);", privateRead);
  assert.ok(privateEffectStart > 0 && privateEffectEnd > privateRead,
    "La consulta privada debe permanecer dentro de un efecto aislado");
  const privateEffect = map.slice(privateEffectStart, privateEffectEnd);
  assert.match(privateEffect, /if \(!realLocator \|\| !canPublish\) return;/,
    "Solo quien tiene MANAGE consulta los recibos privados GIS");
  assert.match(privateEffect, /listManagementCampaigns\(realLocator\)/);
  assert.match(privateEffect, /listGISImports\(realLocator\)/);
  assert.match(map, /Elegir un levantamiento/);
  assert.match(map, /Comparación por fechas \(próximamente\)/);
  assert.match(map, /id="comparison-date"[\s\S]*?disabled/);
});

test("satellite stays as Google basemap while RGB transparency changes without refetch", () => {
  const google = file("../src/components/GoogleSatelliteViewer.tsx");
  assert.match(google, /mapTypeId: "satellite"/);
  assert.match(google, /mapTypeControl: false/);
  assert.match(google, /tileSize: new google\.maps\.Size\(256, 256\)/);
  assert.match(google, /function authorizedRasterOverlay\(/);
  assert.match(google, /setOpacity\(value\) \{/);
  assert.match(google, /for \(const tile of pending\.keys\(\)\) tile\.style\.opacity = String\(opacity\)/);
  assert.match(google, /\}, \[rasterOpacity\]\);/);
  assert.match(google, /const rgbVisible = rasterOpacity > 0/);
  assert.match(google, /const overlays = rgbVisible\s*\? entries\.map\(entry => authorizedRasterOverlay/);
  assert.match(google, /: \[\];\s*overlaysRef\.current = overlays;/);
  assert.match(google, /\}, \[entries, ready, tenantRef, rgbVisible, tileRetryVersion\]\);/);
  assert.match(map, /rgbOverlayOpacity === 0/);
  assert.match(map, /no se descargan sus mosaicos/);
  // Con >0 se reutilizan los tiles y sólo cambia el CSS.
  assert.doesNotMatch(google, /\}, \[entries, ready, tenantRef, rasterOpacity\]\);/);
  assert.match(google, /for \(const overlay of overlaysRef\.current\) overlay\.dispose\(\)/);
  assert.match(google, /mapLibreDbiHeaders\(tenantRef\)/);
  assert.match(map, /rasterOpacity=\{rgbOverlayOpacity \/ 100\}/);
  assert.match(map, /id="dbi-rgb-opacity"/);
  assert.match(map, /setRGBOverlayOpacity\(Number\(event\.target\.value\)\)/);
  assert.match(map, /\{displayEntries\.length > 0 && \(\s*<label className="dbi-rgb-opacity-control"/);
  assert.match(styles, /\.dbi-rgb-opacity-control input:focus-visible/);
  assert.doesNotMatch(google, /roadmap|hybrid|Math\.random/);
});

test("Google SDK failure retains scoped client map evidence with truthful neutral fallback", () => {
  const google = file("../src/components/GoogleSatelliteViewer.tsx");
  assert.match(google, /onUnavailableRef\.current\?\.\(err\.message\)/);
  assert.match(google, /loadGoogleMaps\(apiKey\)/);
  assert.match(google, /googleSDKPromise = null/);
  assert.match(map, /const googleConfigured = Boolean\(import\.meta\.env\.VITE_GOOGLE_MAPS_API_KEY\?\.trim\(\)\)/);
  assert.match(map, /const scopedGoogleFailure = googleFailure\?\.scopeKey === gisScopeKey/);
  assert.match(map, /const useGoogleBase = googleConfigured && !scopedGoogleFailure/);
  assert.match(map, /onUnavailable=\{\(reason\) => setGoogleFailure\(\{ scopeKey: gisScopeKey, reason \}\)\}/);
  assert.match(map, /if \(useGoogleBase \|\| !mapContainerRef\.current \|\| mapRef\.current\) return;/);
  assert.match(map, /Fondo satelital de Google no configurado/);
  assert.match(map, /Se muestran las fotografías y capas cartográficas/);
  assert.match(map, /onClick=\{\(\) => setGoogleFailure\(null\)\}/);
  assert.match(map, /Reintentar Google Satélite/);
  assert.match(styles, /\.dbi-map-google-fallback button:focus-visible/);
  assert.doesNotMatch(map, /fakeGoogle|staticSatelliteImage|Math\.random/);
});

test("map-first workspace renders real chronological visits without mock diagnoses", () => {
  assert.match(map, /producerMapVisits\(/);
  assert.match(map, /visitsAtDate\(mapVisits, selectedDate\)/);
  assert.match(map, /id="dbi-map-view"/);
  assert.match(map, /className="dbi-map-history"/);
  assert.match(map, /aria-label="Elegir levantamiento por fecha"/);
  assert.match(map, /onClick=\{\(\) => chooseMapVisit\(visit\.campaignId, visit\.capturedAt\)\}/);
  assert.match(map, /olderVisit && chooseMapVisit\(olderVisit\.campaignId, olderVisit\.capturedAt\)/);
  assert.match(map, /newerVisit && chooseMapVisit\(newerVisit\.campaignId, newerVisit\.capturedAt\)/);
  assert.match(map, /ambiguousMapDate/);
  assert.match(map, /Imagen RGB disponible; no implica que el análisis técnico esté aprobado/);
  assert.match(map, /Fondo satelital de Google no configurado/);
  assert.match(map, /dbi-map-legend/);
  assert.ok(map.indexOf('id="dbi-map-view"') < map.indexOf('className="dbi-map-history"'));
  assert.ok(map.indexOf('className="dbi-map-history"') < map.indexOf('className="dbi-info-tabs"'));
  assert.match(styles, /\.dbi-map-history-visit\[aria-pressed="true"\]/);
  assert.match(styles, /\.dbi-history-arrow:disabled/);
  assert.match(map, /No se simulan imágenes ni resultados/);
  assert.doesNotMatch(map, /Math\.random\(|mockCover|fakeMapHealth|fakeCampaign/);
});

test("mobile quick date and side date share Campaign reset, not an inferred flight", () => {
  assert.match(map, /const selectPrimaryMapDate = \(date: string\) => \{\s*manuallySelectedVisitRef\.current = true;\s*setSelectedDate\(date\);\s*setSpecificMapCampaign\(null\);/);
  const actions = map.match(/onChange=\{\(event\) => selectPrimaryMapDate\(event\.target\.value\)\}/g) ?? [];
  assert.equal(actions.length, 2, "El selector rápido y el lateral usan la misma regla de Campaign");
  assert.match(map, /id="dbi-mobile-date"/);
  assert.match(map, /disabled=\{dates\.length === 0\}/);
  assert.match(map, /dates\.map\(date => \(/);
  assert.match(map, /aria-label="Accesos rápidos del visor"/);
  assert.match(map, /href="#dbi-map-view"/);
  assert.match(map, /href="#dbi-tab-tracking" onClick=\{\(\) => setInfoTab\("tracking"\)\}/);
  assert.match(map, /realLocator && <a href="#dbi-multi-evidence"/);
  assert.match(map, /id="dbi-map-view"/);
  assert.match(multi, /id="dbi-multi-evidence"/);
});

test("mobile controls are visibly accessible only at phone breakpoint", () => {
  assert.match(styles, /\.dbi-mobile-toolbar \{\s*display: none;/);
  assert.match(styles, /@media \(max-width: 767px\) \{[\s\S]*?\.dbi-mobile-toolbar \{\s*display: grid;/);
  assert.match(styles, /\.dbi-mobile-toolbar select \{[\s\S]*?min-height: 44px;/);
  assert.match(styles, /\.dbi-mobile-shortcuts a:focus-visible/);
  assert.match(styles, /\.dbi-map-stage,[\s\S]*?\.dbi-multi-panel \{\s*scroll-margin-top: 16px;/);
});

test("producer sees factual readout, not an inferred health score", () => {
  assert.match(multi, /aria-label="Lectura rápida para el productor"/);
  assert.match(multi, /Fecha de vuelo no verificada/);
  assert.match(multi, /verifiedFlight && selected\.captured_at/);
  assert.match(multi, /payload\.support_mode === "copa_up"/);
  assert.match(multi, /no representa hectáreas ni porcentaje/);
  assert.match(multi, /coverageLabel\(item\)/);
  assert.match(multi, /INDEX_EXPLANATIONS\[ref\]/);
  assert.match(multi, /<details className="dbi-producer-details">/);
  assert.match(multi, /P10–P90 = intervalo/);
  assert.match(styles, /\.dbi-producer-facts/);
});

test("coverage only reports valid source pixel counts; no hectare or plant inference", () => {
  assert.match(coverageLabel({ selected_count: 100, valid_count: 80, valid_fraction: 0.8 }), /80 de 100 píxeles válidos \(80%\)/);
  assert.equal(coverageLabel({ selected_count: 0, valid_count: 0, valid_fraction: 0 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 2, valid_count: 3, valid_fraction: 1 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 5, valid_count: -1, valid_fraction: 0 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: Number.NaN, valid_count: 1, valid_fraction: 0.5 }),
    "Cobertura de píxeles no disponible");
  assert.equal(coverageLabel({ selected_count: 10, valid_count: 5, valid_fraction: Number.NaN }),
    "5 de 10 píxeles válidos");
  assert.equal(coverageLabel({ selected_count: 10, valid_count: 5, valid_fraction: 1.2 }),
    "5 de 10 píxeles válidos");
  assert.equal(Object.keys(INDEX_EXPLANATIONS).length, 6);
  for (const value of Object.values(INDEX_EXPLANATIONS)) {
    assert.ok(value.length > 20, "Debe haber explicación por índice");
    assert.doesNotMatch(value, /tratamiento recomendado|cultivo enfermo|cultivo sano/i);
  }
});

test("tracking is an accessible tab INSIDE map viewer and MULTI remains mounted", () => {
  assert.match(map, /useState<"multi" \| "tracking">\("tracking"\)/);
  assert.match(map, /className="dbi-info-tabs"/);
  assert.match(map, /role="tablist" aria-label="Pestañas de información agrícola"/);
  assert.match(map, /role="tab"\s+id="dbi-tab-multi"/);
  assert.match(map, /role="tab"\s+id="dbi-tab-tracking"/);
  assert.match(map, /aria-selected=\{infoTab === "multi"\}/);
  assert.match(map, /aria-selected=\{infoTab === "tracking"\}/);
  assert.match(map, /event\.key !== "ArrowRight" && event\.key !== "ArrowLeft"/);
  assert.match(map, /id="dbi-panel-multi"[\s\S]*?hidden=\{infoTab !== "multi"\}/);
  assert.match(map, /id="dbi-panel-tracking"[\s\S]*?hidden=\{infoTab !== "tracking"\}/);
  assert.match(map, /<FarmTrackingPanel[\s\S]*?visibleMapEntries=\{visibleEntries\}/);
  assert.match(map, /<MultispectralEvidencePanel[\s\S]*?selectedMapCampaignId=\{selectedMapCampaignId\}/);
  assert.ok(map.indexOf('id="dbi-map-view"') < map.indexOf('className="dbi-info-tabs"'),
    "El mapa permanece fuera de las pestañas y no se desmonta");
  assert.match(styles, /\.dbi-info-tab-panel\[hidden\] \{\s*display: none !important;/);
  assert.match(styles, /\.dbi-info-tabs \{\s*grid-area: details;/);
  assert.match(styles, /grid-template-areas: "map" "history" "details" "controls"/);
  assert.match(styles, /grid-template-areas: "controls map details" "controls history details"/);
});

test("tracking only describes authorized visible entries and GIS, not diagnoses", () => {
  assert.match(tracking, /import type \{ MapTimelineEntry, PlotMapTimelineLocator \}/);
  assert.match(tracking, /import type \{ VectorLayerInfo \}/);
  assert.match(tracking, /visibleMapEntries: readonly MapTimelineEntry\[\]/);
  assert.match(tracking, /associatedGISLayers: readonly VectorLayerInfo\[\]/);
  assert.match(tracking, /visibleMapEntries\.filter\([\s\S]*?entry\.layer_type === "inspections"/);
  assert.match(tracking, /layer\.layer_kind === "observations"/);
  assert.match(tracking, /No hay registros cartográficos activados para esta selección/);
  assert.match(tracking, /no inspecciones individuales verificadas/);
  assert.match(tracking, /Todavía no has elegido un vuelo/);
  assert.match(tracking, /onOpenEvidence/);
  assert.match(tracking, /role="status"/);
  assert.match(tracking, /role="alert"/);
  assert.doesNotMatch(tracking, /api\.get\(|fetch\(|localStorage|setInterval/);
});

test("INSPECT public view is Campaign-scoped while UUID lookup remains internal", () => {
  assert.match(map, /locator=\{realLocator\}/);
  assert.doesNotMatch(tracking, /<InspectionObservationLookup/);
  assert.match(tracking, /<ApprovedInspectionCampaignPanel/);
  assert.match(approvedInspect, /No hay inspecciones publicadas disponibles/);
  assert.match(tracking, /\{locator && \(/);
  assert.match(inspect, /onSubmit=\{event => \{/);
  assert.match(inspect, /isObservationUUID\(observationId\)/);
  assert.match(inspect, /api\.get<INSPECTReadVersion>/);
  assert.match(inspect, /headers: \{ "X-DBI-Tenant": locator\.tenantRef \}/);
  assert.match(inspect, /inspectionVersionMatchesScope\(data, locator, observationId\)/);
  assert.match(inspect, /requestSequence\.current/);
  assert.match(inspect, /No existe una observación consultable con ese ID/);
  assert.match(inspect, /no se atribuye a la Campaign del mapa/);
  assert.doesNotMatch(inspect, /api\.post|localStorage|IndexedDB|setInterval/);
});

test("INSPECT cross-tenant, cross-plot, or wrong ID is rejected before showing observation", () => {
  const id = "12345678-1234-1234-1234-1234567890ab";
  const versionId = "12345678-1234-1234-1234-1234567890ac";
  const locator = {
    tenantRef: "tenant-alpha",
    organizationRef: "org-a",
    farmId: "11111111-1111-1111-1111-111111111111",
    plotId: "22222222-2222-2222-2222-222222222222",
  };
  const observed = { state: "observed", value: 3, reason: null };
  const record = {
    schema_version: "dbi-field-observation.v1",
    observation_id: id,
    version_id: versionId,
    version: 1,
    created_at: "2026-09-01T08:00:00Z",
    payload: {
      tenant_ref: locator.tenantRef,
      organization_ref: locator.organizationRef,
      farm_id: locator.farmId,
      plot_id: locator.plotId,
      observed_at: "2026-09-01T07:00:00Z",
      evidence_kind: "observed",
      sampling_point_id: null,
      up_id: null,
      gps_fix: null,
      core: { foure: observed, yls: observed, functional_leaves: observed },
    },
  };
  assert.equal(isObservationUUID(id), true);
  assert.equal(isObservationUUID("bad-or-leaked-url"), false);
  assert.equal(inspectionVersionMatchesScope(record, locator, id), true);
  assert.equal(inspectionVersionMatchesScope(record, locator, versionId), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, observation_id: versionId }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, tenant_ref: "tenant-beta" } }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, organization_ref: "org-b" } }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, farm_id: "33333333-3333-3333-3333-333333333333" } }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, plot_id: "44444444-4444-4444-4444-444444444444" } }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, evidence_kind: "derived" } }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, version: 0 }, locator, id), false);
  assert.equal(inspectionVersionMatchesScope({ ...record, payload: { ...record.payload, core: null } }, locator, id), false);
});

test("H13 producer navigation uses readable flight labels while retaining exact scoped IDs internally", () => {
  assert.match(map, /Levantamiento específico seleccionado/);
  assert.match(map, /Levantamiento elegido/);
  assert.doesNotMatch(map, /selectedMapCampaignId\.slice\(0, 8\)/);
  assert.match(multi, /verifiedHistory\.map\(\(entry, index\) =>/);
  assert.match(multi, /Vuelo \{index \+ 1\}/);
  assert.match(multi, /onChooseVerifiedCampaign\(entry\.campaignId, entry\.capturedAt\)/);
  assert.match(multi, /Muestra \{index \+ 1\}/);
  assert.match(multi, /value=\{item\.extraction_id\}/);
  assert.doesNotMatch(multi, /entry\.campaignId\.slice\(0, 8\)/);
  assert.doesNotMatch(multi, /item\.extraction_id\.slice\(0, 8\)/);
  assert.doesNotMatch(multi, /\{selected\.campaign_id\}|\{payload\.observation_version_id\}|\{payload\.source_raster_product_id\}/);
  assert.match(tracking, /selectedCampaignId \? "Vuelo específico elegido" : "Todavía no has elegido un vuelo"/);
  assert.match(tracking, /campaignId=\{selectedCampaignId\}/);
  assert.doesNotMatch(tracking, /\{selectedCampaignId \?\?/);
  assert.match(styles, /\.dbi-tracking-selection-chip/);
  assert.match(styles, /#fff7ee/);
  assert.doesNotMatch(multi, /Math\.random\(|fakeCampaign|mockInspection/);
});

test("INSPECT missing data remain missing rather than healthy or diseased", () => {
  assert.equal(observedNumberLabel({ state: "observed", value: 0, reason: null }), "0");
  assert.equal(observedNumberLabel({ state: "observed", value: 5, reason: null }), "5");
  assert.equal(observedNumberLabel({ state: "not_measured", value: null, reason: "not_visited" }), "No medido");
  assert.equal(observedNumberLabel({ state: "not_applicable", value: null, reason: "no_bunch" }), "No aplicable");
  assert.equal(observedNumberLabel({ state: "observed", value: Number.NaN, reason: null }), "Dato no disponible");
});

test("client landing view uses DALGORO brand and safe retry of authorized catalogue", () => {
  assert.match(clientHome, /className="dbi-portal-hero/);
  assert.match(styles, /\.dbi-portal-home \.dbi-portal-hero/);
  assert.match(styles, /#152e32/);
  assert.match(styles, /#b57b50/);
  assert.match(clientHome, /api\.get<Account\[\]>\(/);
  assert.match(clientHome, /"\/api\/v1\/dbi\/portal\/accounts"/);
  assert.match(clientHome, /setLoading\(true\);[\s\S]*?setError\(null\);/);
  assert.match(clientHome, /\}, \[reloadKey\]\);/);
  assert.match(clientHome, /onClick=\{retry\}/);
  assert.match(clientHome, /Reintentar consulta/);
  assert.match(clientHome, /role="alert"/);
  assert.match(clientHome, /aria-live="polite"/);
  assert.match(clientHome, /const totalPlots = farms\.reduce/);
  assert.match(clientHome, /loading \|\| error \? "—" : farms\.length/);
  assert.match(clientHome, /loading \|\| error \? "—" : totalPlots/);
  assert.match(clientHome, /mapLink\(account, farm, plot\)/);
  assert.doesNotMatch(clientHome, /Math\.random|fakeCampaign|mockPlots|api\.post\(/);
});

test("client sees six verified index controls and PDF only after publication", () => {
  const report = file("../src/components/PublishedCampaignPDFPanel.tsx");
  for (const name of ["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"]) {
    assert.match(multi, new RegExp(name));
  }
  assert.match(multi, /checked=\{visibleIndices\.has\(ref\)\}/);
  assert.match(map, /Seis mapas multiespectrales/);
  assert.match(map, /disabled aria-label=\{\`Mapa/);
  assert.match(map, /Población y resultados GIS del levantamiento/);
  assert.match(tracking, /<PublishedCampaignPDFPanel/);
  assert.match(report, /published-evidence\.pdf/);
  assert.match(report, /responseType: "blob"/);
  assert.match(report, /URL\.revokeObjectURL\(state\.url\)/);
  assert.match(report, /Todavía no hay una ficha PDF aprobada y publicada/);
  assert.doesNotMatch(report, /mockData|fakePDF|Math\.random/);
});

test("approved INSPECT panel only reads public Campaign-specific values without user UUID", () => {
  assert.match(tracking, /<ApprovedInspectionCampaignPanel/);
  assert.match(tracking, /campaignId=\{selectedCampaignId\}/);
  assert.match(approvedInspect, /published-inspections/);
  assert.match(approvedInspect, /"X-DBI-Tenant": tenantRef/);
  assert.match(approvedInspect, /if \(!campaignId\)/);
  assert.match(approvedInspect, /sequence\.current !== current/);
  assert.match(approvedInspect, /setRefreshKey\(key => key \+ 1\)/);
  assert.match(approvedInspect, /No hay inspecciones publicadas disponibles/);
  assert.match(approvedInspect, /observedNumberLabel/);
  assert.match(approvedInspect, /No medido/);
  assert.match(approvedInspect, /role="alert"/);
  assert.doesNotMatch(approvedInspect, /field-observations|observation_id|version_id|gps_fix|payload_json/);
  assert.doesNotMatch(approvedInspect, /api\.post\(|Math\.random\(|mockInspection/);
});

test("neutral fallback keeps the producer's RGB opacity and does not fetch hidden tiles", () => {
  assert.match(map, /const rgbOverlayVisible = rgbOverlayOpacity > 0/);
  assert.match(map, /for \(const entry of \(rgbOverlayVisible \? displayEntries : \[\]\)\)/);
  assert.match(map, /\}, \[displayEntries, mapReady, rgbOverlayVisible\]\);/);
  assert.match(map, /map\.setPaintProperty\(id, "raster-opacity", rgbOverlayOpacity \/ 100\)/);
  assert.match(map, /\}, \[mapReady, rgbOverlayOpacity\]\);/);
  assert.match(map, /Fotografía RGB sobre fondo neutro/);
  assert.match(map, /Solo fondo neutro: la ortofoto está oculta y no se descargan sus mosaicos/);
});

test("producer map orientation links to an existing authorized portal and does not replace map visits", () => {
  const scopedStyle = file("../src/pages/farm-map-ux.css");
  assert.match(map, /<Link to="\/portal">Mis fincas<\/Link>/);
  assert.match(map, /aria-label="Ubicación dentro del portal"/);
  assert.match(map, /aria-label="Levantamiento seleccionado"/);
  assert.match(map, /selectedVisit\s*\? selectedVisit\.name/);
  assert.match(map, /selectedVisit\.gisLayerCount/);
  assert.match(map, /ambiguousMapDate[\s\S]*?"Elige un vuelo de esta fecha"/);
  assert.match(map, /Solo se muestran levantamientos con cartografía autorizada/);
  assert.match(map, /href="#dbi-map-view">Ver mapa/);
  assert.match(map, /href="#dbi-map-history">Cambiar vuelo/);
  assert.match(map, /\{active && <span className="dbi-map-history-current">Seleccionado<\/span>\}/);
  assert.match(map, /onClick=\{\(\) => chooseMapVisit\(visit\.campaignId, visit\.capturedAt\)\}/);
  assert.match(scopedStyle, /\.dbi-map-selection-actions a \{[\s\S]*?min-height:\s*44px/);
  assert.match(scopedStyle, /\.dbi-map-selection-actions a:focus-visible/);
  assert.match(scopedStyle, /@media \(max-width: 720px\)/);
  assert.match(scopedStyle, /\.dark \.dbi-map-selection-summary/);
  assert.doesNotMatch(map, /fakeCampaign|fakeMapHealth|mockCover|Math\.random\(/);
});

test("producer index cards separate measured median, percentile interval and interpretation", () => {
  const cardCss = file("../src/components/dbi-multi-readout-guide.css");
  assert.match(multi, /aria-label="Cómo interpretar una ficha de índice"/);
  assert.match(multi, /Mediana de la muestra/);
  assert.match(multi, /Intervalo P10–P90/);
  assert.match(multi, /percentileIntervalLabel\(item\)/);
  assert.match(multi, /hasValidMedian && item \? number\(item\.median\) : "No disponible"/);
  assert.match(multi, /Cobertura de píxeles no disponible/);
  assert.match(multi, /Qué describe/);
  assert.match(multi, /INDEX_EXPLANATIONS\[ref\]/);
  assert.match(multi, /No identifica por sí solo enfermedades, causas ni tratamientos/);
  assert.match(multi, /no la salud completa del cultivo/);
  assert.match(cardCss, /\.dbi-index-measurement-value/);
  assert.match(cardCss, /\.dbi-index-evidence-card/);
  assert.match(cardCss, /\.dark \.dbi-multi-readout-intro/);
  assert.match(cardCss, /@media \(max-width: 480px\)/);
  assert.doesNotMatch(multi, /healthScore|diseaseRisk|trafficLight|predictedYield|Math\.random/);
});

test("percentile presentation hides missing, nonfinite and inconsistent index measurements", () => {
  const sample = { selected_count: 100, valid_count: 80, p10: 0.2, p90: 0.8 };
  assert.match(percentileIntervalLabel(sample), /0[,.]2 – 0[,.]8/);
  assert.equal(percentileIntervalLabel({ ...sample, valid_count: 0 }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, valid_count: 101 }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, selected_count: 0 }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, p10: null }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, p90: Number.NaN }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, p10: 0.9 }), "Intervalo no disponible");
  assert.equal(percentileIntervalLabel({ ...sample, p10: 0.5, p90: 0.5 }), "0,5 – 0,5");
});

test("mobile MULTI keeps six real evidence cards with swipe or full list, never fabricated metrics", () => {
  const mobileCss = file("../src/components/dbi-multi-readout-guide.css");
  assert.match(multi, /const \[expandedMobileIndices, setExpandedMobileIndices\] = useState\(false\)/);
  assert.match(multi, /aria-label="Presentación móvil de los índices"/);
  assert.match(multi, /Desliza para consultar cada índice de esta muestra/);
  assert.match(multi, /onClick=\{\(\) => setExpandedMobileIndices\(current => !current\)\}/);
  assert.match(multi, /aria-pressed=\{expandedMobileIndices\}/);
  assert.match(multi, /aria-controls="dbi-multi-index-cards"/);
  assert.match(multi, /expandedMobileIndices \? "Vista compacta" : "Ver todos"/);
  assert.match(multi, /data-mobile-layout=\{expandedMobileIndices \? "list" : "carousel"\}/);
  assert.match(multi, /aria-label="Fichas de los índices derivados de la muestra seleccionada"/);
  assert.match(multi, /tabIndex=\{0\}/);
  assert.match(multi, /Object\.entries\(INDEX_LABELS\)\.filter\(\(\[ref\]\) => visibleIndices\.has\(ref\)\)/);
  assert.match(mobileCss, /@media \(max-width: 767px\)/);
  assert.match(mobileCss, /grid-auto-flow: column/);
  assert.match(mobileCss, /scroll-snap-type: x proximity/);
  assert.match(mobileCss, /data-mobile-layout="list"/);
  assert.match(mobileCss, /\.dbi-multi-mobile-tools button:focus-visible/);
  assert.match(mobileCss, /min-height: 44px/);
  assert.match(mobileCss, /@media \(max-width: 390px\)/);
  assert.match(mobileCss, /\.dark \.dbi-multi-mobile-tools button/);
  assert.doesNotMatch(multi, /healthScore|diseaseRisk|trafficLight|predictedYield|mockIndex|Math\.random\(/);
});
