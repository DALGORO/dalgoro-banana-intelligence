/** Inventario local H14: metadatos de carpetas, nunca contenido/bytes ni publicación. */
export type AnalysisFolderKind = "geospatial" | "multispectral";
export const INDEX_REFS = [
  "ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green",
] as const;
export type IndexRef = typeof INDEX_REFS[number];
export type FolderFileMetadata = Pick<File, "name" | "size" | "webkitRelativePath">;
export type FolderEntry = {
  path: string;
  role: string;
  status: "candidate" | "review" | "excluded";
  note: string;
};
export type FolderInventory = {
  kind: AnalysisFolderKind;
  rootName: string | null;
  totalFiles: number;
  entries: FolderEntry[];
  issues: string[];
  missing: string[];
  candidateCount: number;
  reviewCount: number;
  excludedCount: number;
  /** Solo nombre/ruta/tamaño inspeccionados: nunca afirmar validación científica. */
  scientificValidated: false;
  uploaded: false;
  published: false;
};

const MAX_FILES = 1500;
const TOKEN_RULES: ReadonlyArray<readonly [IndexRef, RegExp]> = [
  ["ci_red_edge", /(?:^|_)(?:ci_red_edge|ci_re|chlorophyll_red_edge)(?:_|$)/],
  ["ci_green", /(?:^|_)(?:ci_green|ci_gr|chlorophyll_green)(?:_|$)/],
  ["gndvi", /(?:^|_)gndvi(?:_|$)/],
  ["ndre", /(?:^|_)ndre(?:_|$)/],
  ["ndvi", /(?:^|_)ndvi(?:_|$)/],
  ["evi2", /(?:^|_)evi_?2(?:_|$)/],
];

function normalized(path: string): string {
  return path.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function spectralIndex(path: string): IndexRef | null {
  // Nombre antes que directorios: una carpeta con varios índices no altera
  // las identidades claras de los ficheros contenidos.
  const segments = path.split("/");
  const filename = normalized(segments.at(-1) ?? "");
  const matches = TOKEN_RULES.filter(([, re]) => re.test(filename)).map(([key]) => key);
  if (matches.length === 1) return matches[0];
  if (matches.length > 1) return null;
  const parent = normalized(segments.slice(1, -1).join("_"));
  const parentMatches = TOKEN_RULES.filter(([, re]) => re.test(parent)).map(([key]) => key);
  return parentMatches.length === 1 ? parentMatches[0] : null;
}

function classifyGeo(path: string): Omit<FolderEntry, "path"> {
  const name = path.split("/").at(-1) ?? "";
  const extension = name.toLowerCase().split(".").at(-1) ?? "";
  const stem = normalized(name.replace(/\.[^.]+$/, ""));
  if (["tif", "tiff"].includes(extension)) {
    if (/(?:^|_)(rgb|ortho|ortofoto|orthomosaic|mosaico)(?:_|$)/.test(stem)) {
      return { role: "Ortofoto RGB", status: "candidate", note: "Solo nombre: confirmar bandas, CRS y Campaign en servidor." };
    }
    return { role: "Ráster sin tipo confirmado", status: "review", note: "No se puede inferir RGB ni ciencia solo por .tif." };
  }
  if (extension === "gpkg") {
    return { role: "GeoPackage", status: "review", note: "El servidor debe descubrir y validar cada capa interior." };
  }
  if (extension === "zip") {
    return { role: "Archivo GIS comprimido", status: "review", note: "Validar contenido ZIP y formato SHP antes de usar." };
  }
  if (extension === "geojson" || extension === "json") {
    return { role: "GeoJSON o JSON", status: "review", note: "Validar tipo, geometría, CRS y clase antes de ofrecer al cliente." };
  }
  if (extension === "pdf") {
    return { role: "Informe PDF", status: "review", note: "Requiere identidad de campaña y aprobación del documento." };
  }
  if (["shp", "shx", "dbf", "prj"].includes(extension)) {
    return { role: "Componente Shapefile", status: "review", note: "Agrupar/validar conjunto SHP en el servidor; no publicarlo suelto." };
  }
  if (["qml", "qmd", "tfw", "ovr", "aux", "xml"].includes(extension)) {
    return { role: "Archivo auxiliar", status: "review", note: "Archivo de apoyo; no es por sí solo una capa publicable." };
  }
  return { role: "No reconocido", status: "excluded", note: "No se enviará automáticamente en la futura carga." };
}

function classifyMulti(path: string): Omit<FolderEntry, "path"> {
  const extension = path.split("/").at(-1)?.toLowerCase().split(".").at(-1) ?? "";
  const index = spectralIndex(path);
  if (["tif", "tiff", "qml"].includes(extension)) {
    if (!index) return { role: "Índice ambiguo", status: "review", note: "No hay identidad única verificable por nombre/carpeta." };
    if (extension === "qml") {
      return { role: `${index} · estilo QML`, status: "candidate", note: "Pendiente de validar rampa, banda y SHA-256 real." };
    }
    return { role: `${index} · ráster científico`, status: "candidate", note: "Pendiente de comprobar Float32, COG, fórmula y grilla en servidor." };
  }
  return { role: "Archivo complementario", status: "excluded", note: "No forma parte del par COG/QML verificable." };
}

export function inventoryFolder(kind: AnalysisFolderKind, files: readonly FolderFileMetadata[]): FolderInventory {
  const issues: string[] = [];
  const entries: FolderEntry[] = [];
  const missing: string[] = [];
  if (files.length > MAX_FILES) issues.push(`La carpeta supera ${MAX_FILES} archivos: requiere una importación dividida.`);
  const roots = new Set<string>();
  const paths = new Set<string>();
  for (const file of files.slice(0, MAX_FILES)) {
    const path = file.webkitRelativePath;
    const segments = path?.split("/") ?? [];
    if (
      !path || segments.length < 2
      || segments.some(segment => !segment || segment === "." || segment === ".."
        || Array.from(segment).some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127))
      || !Number.isSafeInteger(file.size) || file.size < 0
      || file.name !== segments.at(-1)
    ) {
      issues.push("Hay archivos sin ruta relativa de carpeta válida; revisa compatibilidad del navegador.");
      continue;
    }
    if (paths.has(path.toLowerCase())) {
      issues.push("Existen rutas duplicadas; no se puede distinguir su identidad.");
      continue;
    }
    paths.add(path.toLowerCase());
    roots.add(segments[0]);
    const classified = kind === "geospatial" ? classifyGeo(path) : classifyMulti(path);
    entries.push({ path, ...classified });
  }
  if (roots.size > 1) issues.push("La selección contiene más de una carpeta raíz.");
  if (files.length === 0) issues.push("No se han seleccionado archivos.");
  if (entries.length === 0 && files.length > 0) issues.push("No se pudo reconocer ningún archivo de esta carpeta.");
  const recognized = (role: string) => entries.filter(x => x.role === role && x.status === "candidate").length;
  if (kind === "multispectral") {
    for (const index of INDEX_REFS) {
      for (const [label, suffix] of [["COG", "ráster científico"], ["QML", "estilo QML"]] as const) {
        const count = recognized(`${index} · ${suffix}`);
        if (count === 0) missing.push(`${index.toUpperCase()} · ${label}`);
        if (count > 1) issues.push(`Hay ${count} archivos candidatos para ${index.toUpperCase()} · ${label}; se requiere selección inequívoca.`);
      }
    }
    if (entries.some(item => item.role === "Índice ambiguo")) {
      issues.push("Uno o más TIFF/QML carecen de un índice inequívoco.");
    }
  } else if (recognized("Ortofoto RGB") > 1) {
    issues.push("Varias ortofotos RGB candidatas: el administrador deberá elegir la correspondiente al vuelo.");
  }
  return {
    kind, rootName: roots.size === 1 ? [...roots][0] : null,
    totalFiles: files.length, entries, issues, missing,
    candidateCount: entries.filter(x => x.status === "candidate").length,
    reviewCount: entries.filter(x => x.status === "review").length,
    excludedCount: entries.filter(x => x.status === "excluded").length,
    scientificValidated: false, uploaded: false, published: false,
  };
}
