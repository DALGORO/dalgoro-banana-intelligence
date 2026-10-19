import type { MultispectralSummary } from "./multispectralEvidence";

/**
 * Ayudas de lectura para productores: solo describen datos persistidos.
 * No interpretan vigor, enfermedades, productividad ni dosis de tratamiento.
 */
export const INDEX_EXPLANATIONS: Record<string, string> = {
  ndvi: "Combina reflectancia roja e infrarroja cercana para describir una señal espectral de vegetación.",
  ndre: "Combina borde rojo e infrarrojo cercano; puede apoyar una revisión técnica, pero no mide clorofila en campo.",
  gndvi: "Combina verde e infrarrojo cercano para describir una respuesta espectral de vegetación.",
  evi2: "Índice espectral de vegetación calculado con dos bandas; no equivale a rendimiento de cosecha.",
  ci_red_edge: "Índice espectral basado en borde rojo; no confirma por sí solo nutrición ni deficiencias.",
  ci_green: "Índice espectral basado en verde; no confirma por sí solo nutrición ni deficiencias.",
};

export function coverageLabel(summary: Pick<MultispectralSummary,
  "selected_count" | "valid_count" | "valid_fraction">): string {
  const { selected_count: total, valid_count: valid, valid_fraction: fraction } = summary;
  if (!Number.isSafeInteger(total) || total <= 0
    || !Number.isSafeInteger(valid) || valid < 0 || valid > total) {
    return "Cobertura de píxeles no disponible";
  }
  const proportion = Number.isFinite(fraction) && fraction >= 0 && fraction <= 1
    ? " (" + (fraction * 100).toLocaleString("es-EC", { maximumFractionDigits: 1 }) + "%)"
    : "";
  return `${valid.toLocaleString("es-EC")} de ${total.toLocaleString("es-EC")} píxeles válidos${proportion}`;
}

/**
 * Intervalo descriptivo P10–P90 de UNA extracción, no escala de vigor.
 * Se rechazan contadores incoherentes y límites no finitos o invertidos.
 * No se promedian campañas, convierten unidades ni infieren diagnósticos.
 */
export function percentileIntervalLabel(summary: Pick<MultispectralSummary,
  "selected_count" | "valid_count" | "p10" | "p90">): string {
  const { selected_count: selected, valid_count: valid, p10, p90 } = summary;
  if (!Number.isSafeInteger(selected) || selected <= 0
    || !Number.isSafeInteger(valid) || valid <= 0 || valid > selected
    || p10 === null || p90 === null
    || !Number.isFinite(p10) || !Number.isFinite(p90) || p10 > p90) {
    return "Intervalo no disponible";
  }
  return `${p10.toLocaleString("es-EC", { maximumFractionDigits: 3 })} – ${p90.toLocaleString("es-EC", { maximumFractionDigits: 3 })}`;
}
