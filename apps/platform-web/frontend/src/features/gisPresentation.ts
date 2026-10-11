/** Vistas seguras para las capas GIS compartidas con el cliente. */
import type { VectorLayerKind } from "@/features/portalVectors";

export const GIS_KIND_LABELS: Record<VectorLayerKind, string> = {
  plants: "Ubicación de plantas",
  density_hexagons: "Densidad por sectores",
  planting_candidates: "Oportunidades de siembra",
  boundaries: "Límites de lote",
  observations: "Observaciones de campo",
  other: "Información geográfica",
};

export const GIS_KIND_COLORS: Record<VectorLayerKind, string> = {
  plants: "#059669",
  density_hexagons: "#d97706",
  planting_candidates: "#2563eb",
  boundaries: "#047857",
  observations: "#9333ea",
  other: "#64748b",
};

/** El contenido del GeoJSON nunca se interpola como HTML. */
export function createGISFeatureDetails(
  ownerDocument: Document,
  layerName: string,
  fields: Record<string, unknown>,
): HTMLElement {
  const root = ownerDocument.createElement("div");
  root.style.maxWidth = "280px";
  root.style.minWidth = "170px";
  root.style.fontFamily = "system-ui, sans-serif";

  const heading = ownerDocument.createElement("strong");
  heading.style.display = "block";
  heading.style.marginBottom = "8px";
  heading.textContent = layerName.slice(0, 100);
  root.appendChild(heading);

  let visible = 0;
  for (const [name, value] of Object.entries(fields)) {
    if (visible >= 15) break;
    if (name.startsWith("__dbi_") || !name.trim() || name.length > 60) continue;
    if (value === null || value === undefined || typeof value === "object") continue;
    if (!["string", "number", "boolean"].includes(typeof value)) continue;

    const row = ownerDocument.createElement("div");
    row.style.padding = "5px 0";
    row.style.borderBottom = "1px solid #e2e8f0";

    const label = ownerDocument.createElement("span");
    label.style.display = "block";
    label.style.fontSize = "11px";
    label.style.color = "#475569";
    label.textContent = name;

    const result = ownerDocument.createElement("span");
    result.style.fontSize = "13px";
    result.style.fontWeight = "500";
    result.textContent = String(value).slice(0, 200);

    row.append(label, result);
    root.appendChild(row);
    visible += 1;
  }

  if (visible === 0) {
    const note = ownerDocument.createElement("p");
    note.style.fontSize = "12px";
    note.style.color = "#64748b";
    note.textContent = "Este elemento no tiene atributos adicionales.";
    root.appendChild(note);
  }
  return root;
}
