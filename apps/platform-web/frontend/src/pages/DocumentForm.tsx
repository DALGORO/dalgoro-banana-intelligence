import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { api as axiosApi } from "@/app/api";
import { toast } from "react-toastify";

// === PSICO: multi-trabajador (tipos + helper) ===
type PsicoPack = {
  worker_index: number;                 // 1..N
  fields: Record<string, any>;          // A..I (fecha, provincia, edad, sexo, etc.)
  respuestas: Array<{ nr: number; dimension: string; item: string; puntuacion: number; observacion?: string }>;
  completed?: boolean;                  // marcado localmente
};

function isPsicoComplete(f: Record<string, any>, respuestas: any[]) {
  const req = ["fecha","provincia","ciudad","area_trabajo","nivel_instruccion","antiguedad","edad","etnia","sexo"];
  const okCab = req.every(k => String(f?.[k] ?? "").trim() !== "");
  const okPreg = Array.isArray(respuestas) && respuestas.length === 58 && respuestas.every(r => [1,2,3,4].includes(Number(r?.puntuacion)));
  return okCab && okPreg;
}


// Helper para leer defaults sin importar el nombre de la propiedad (defaults o defaults_json)
const getTplDefaults = (t: any) => (t?.defaults ?? t?.defaults_json ?? {});

// Fallback local con los 58 ítems oficiales (NR, dimensión, descripción, tipo)
const FALLBACK_PSICO_ITEMS = [
  { nr: 1,  dimension: "CARGA Y RITMO DE TRABAJO", item: "Considero que son aceptables las solicitudes y requerimientos que me piden otras personas (compañeros de trabajo, usuarios, clientes)", tipo: "directa" },
  { nr: 2,  dimension: "CARGA Y RITMO DE TRABAJO", item: "Decido el ritmo de trabajo en mis actividades", tipo: "directa" },
  { nr: 3,  dimension: "CARGA Y RITMO DE TRABAJO", item: "Las actividades y/o responsabilidades que me fueron asignadas no me causan estrés", tipo: "directa" },
  { nr: 4,  dimension: "CARGA Y RITMO DE TRABAJO", item: "Tengo suficiente tiempo para realizar todas las actividades que me han sido encomendadas dentro de mi jornada laboral", tipo: "directa" },

  { nr: 5,  dimension: "DESARROLLO DE COMPETENCIAS", item: "Considero que tengo los suficientes conocimientos, habilidades y destrezas para desarrollar el trabajo para el cual fui contratado", tipo: "directa" },
  { nr: 6,  dimension: "DESARROLLO DE COMPETENCIAS", item: "En mi trabajo aprendo y adquiero nuevos conocimientos, habilidades y destrezas de mis compañeros de trabajo", tipo: "directa" },
  { nr: 7,  dimension: "DESARROLLO DE COMPETENCIAS", item: "En mi trabajo se cuenta con un plan de carrera, capacitación y/o entrenamiento para el desarrollo de mis conocimientos, habilidades y destrezas", tipo: "directa" },
  { nr: 8,  dimension: "DESARROLLO DE COMPETENCIAS", item: "En mi trabajo se evalúa objetiva y periódicamente las actividades que realizo", tipo: "directa" },

  { nr: 9,  dimension: "LIDERAZGO", item: "En mi trabajo se reconoce y se da crédito a la persona que realiza un buen trabajo o logra sus objetivos", tipo: "directa" },
  { nr: 10, dimension: "LIDERAZGO", item: "Mi jefe inmediato está dispuesto a escuchar propuestas de cambio e iniciativas de trabajo", tipo: "directa" },
  { nr: 11, dimension: "LIDERAZGO", item: "Mi jefe inmediato establece metas, plazos claros y factibles para el cumplimiento de mis funciones o actividades", tipo: "directa" },
  { nr: 12, dimension: "LIDERAZGO", item: "Mi jefe inmediato interviene, brinda apoyo, soporte y se preocupa cuando tengo demasiado trabajo que realizar", tipo: "directa" },
  { nr: 13, dimension: "LIDERAZGO", item: "Mi jefe inmediato me brinda suficientes lineamientos y retroalimentación para el desempeño de mi trabajo", tipo: "directa" },
  { nr: 14, dimension: "LIDERAZGO", item: "Mi jefe inmediato pone en consideración del equipo de trabajo, las decisiones que pueden afectar a todos", tipo: "directa" },

  { nr: 15, dimension: "MARGEN DE ACCIÓN Y CONTROL", item: "En mi trabajo existen espacios de discusión para debatir abiertamente los problemas comunes y diferencias de opinión", tipo: "directa" },
  { nr: 16, dimension: "MARGEN DE ACCIÓN Y CONTROL", item: "Me es permitido realizar el trabajo con colaboración de mis compañeros de trabajo y/u otras áreas", tipo: "directa" },
  { nr: 17, dimension: "MARGEN DE ACCIÓN Y CONTROL", item: "Mi opinión es tomada en cuenta con respecto a fechas límites en el cumplimiento de mis actividades o cuando exista cambio en mis funciones", tipo: "directa" },
  { nr: 18, dimension: "MARGEN DE ACCIÓN Y CONTROL", item: "Se me permite aportar con ideas para mejorar las actividades y la organización del trabajo", tipo: "directa" },

  { nr: 19, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "Considero que las formas de comunicación en mi trabajo son adecuadas, accesibles y de fácil comprensión", tipo: "directa" },
  { nr: 20, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "En mi trabajo se informa regularmente de la gestión y logros de la empresa o institución a todos los trabajadores y servidores", tipo: "directa" },
  { nr: 21, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "En mi trabajo se respeta y se toma en consideración las limitaciones de las personas con discapacidad para la asignación de roles y tareas", tipo: "directa" },
  { nr: 22, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "En mi trabajo tenemos reuniones suficientes y significantes para el cumplimiento de los objetivos", tipo: "directa" },
  { nr: 23, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "Las metas y objetivos en mi trabajo son claros y alcanzables", tipo: "directa" },
  { nr: 24, dimension: "ORGANIZACIÓN DEL TRABAJO", item: "Siempre dispongo de tareas y actividades a realizar en mi jornada y lugar de trabajo", tipo: "directa" },

  { nr: 25, dimension: "RECUPERACIÓN", item: "Después del trabajo tengo la suficiente energía como para realizar otras actividades", tipo: "directa" },
  { nr: 26, dimension: "RECUPERACIÓN", item: "En mi trabajo se me permite realizar pausas de periodo corto para renovar y recuperar la energía", tipo: "directa" },
  { nr: 27, dimension: "RECUPERACIÓN", item: "En mi trabajo tengo tiempo para dedicarme a reflexionar sobre mi desempeño en el trabajo", tipo: "directa" },
  { nr: 28, dimension: "RECUPERACIÓN", item: "Tengo un horario y jornada de trabajo que se ajusta a mis expectativas y exigencias laborales", tipo: "directa" },
  { nr: 29, dimension: "RECUPERACIÓN", item: "Todos los días siento que he descansado lo suficiente y que tengo la energía para iniciar mi trabajo", tipo: "directa" },

  { nr: 30, dimension: "SOPORTE Y APOYO", item: "El trabajo está organizado de tal manera que fomenta la colaboración de equipo y el diálogo con otras personas", tipo: "directa" },
  { nr: 31, dimension: "SOPORTE Y APOYO", item: "En mi trabajo percibo un sentimiento de compañerismo y bienestar con mis colegas", tipo: "directa" },
  { nr: 32, dimension: "SOPORTE Y APOYO", item: "En mi trabajo se brinda el apoyo necesario a los trabajadores sustitutos o trabajadores con algún grado de discapacidad y enfermedad", tipo: "directa" },
  { nr: 33, dimension: "SOPORTE Y APOYO", item: "En mi trabajo se me brinda ayuda técnica y administrativa cuando lo requiero", tipo: "directa" },
  { nr: 34, dimension: "SOPORTE Y APOYO", item: "En mi trabajo tengo acceso a la atención de un médico, psicólogo, trabajadora social, consejero, etc., en situaciones de crisis y/o rehabilitación", tipo: "directa" },

  { nr: 35, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo tratan por igual a todos, indistintamente la edad que tengan", tipo: "directa" },
  { nr: 36, dimension: "OTROS PUNTOS IMPORTANTES", item: "Las directrices y metas que me autoimpongo, las cumplo dentro de mi jornada y horario de trabajo", tipo: "directa" },
  { nr: 37, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo existe un buen ambiente laboral", tipo: "directa" },
  { nr: 38, dimension: "OTROS PUNTOS IMPORTANTES", item: "Tengo un trabajo donde los hombres y mujeres tienen las mismas oportunidades", tipo: "directa" },
  { nr: 39, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo me siento aceptado y valorado", tipo: "directa" },
  { nr: 40, dimension: "OTROS PUNTOS IMPORTANTES", item: "Los espacios y ambientes físicos en mi trabajo brindan las facilidades para el acceso de las personas con discapacidad", tipo: "directa" },
  { nr: 41, dimension: "OTROS PUNTOS IMPORTANTES", item: "Considero que mi trabajo está libre de amenazas, humillaciones, ridiculizaciones, burlas, calumnias o difamaciones reiteradas con el fin de causarme daño", tipo: "directa" },
  { nr: 42, dimension: "OTROS PUNTOS IMPORTANTES", item: "Me siento estable a pesar de cambios que se presentan en mi trabajo", tipo: "directa" },
  { nr: 43, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo estoy libre de conductas sexuales que afecten mi integridad física, psicológica y moral", tipo: "directa" },
  { nr: 44, dimension: "OTROS PUNTOS IMPORTANTES", item: "Considero que el trabajo que realizo no me causa efectos negativos a mi salud física y mental", tipo: "directa" },
  { nr: 45, dimension: "OTROS PUNTOS IMPORTANTES", item: "Me resulta fácil relajarme cuando no estoy trabajando", tipo: "directa" },
  { nr: 46, dimension: "OTROS PUNTOS IMPORTANTES", item: "Siento que mis problemas familiares o personales no influyen en el desempeño de las actividades en el trabajo", tipo: "directa" },
  { nr: 47, dimension: "OTROS PUNTOS IMPORTANTES", item: "Las instalaciones, ambientes, equipos, maquinaria y herramientas que utilizo para realizar el trabajo son las adecuadas para no sufrir accidentes de trabajo y enfermedades profesionales", tipo: "directa" },
  { nr: 48, dimension: "OTROS PUNTOS IMPORTANTES", item: "Mi trabajo está libre de acoso sexual", tipo: "directa" },
  { nr: 49, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo se me permite solucionar mis problemas familiares y personales", tipo: "directa" },
  { nr: 50, dimension: "OTROS PUNTOS IMPORTANTES", item: "Tengo un trabajo libre de conflictos estresantes, rumores maliciosos o calumniosos sobre mi persona", tipo: "directa" },
  { nr: 51, dimension: "OTROS PUNTOS IMPORTANTES", item: "Tengo un equilibrio y separo bien el trabajo de mi vida personal", tipo: "directa" },
  { nr: 52, dimension: "OTROS PUNTOS IMPORTANTES", item: "Estoy orgulloso de trabajar en mi empresa o institución", tipo: "directa" },
  { nr: 53, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo se respeta mi ideología, opinión política, religiosa, nacionalidad y orientación sexual", tipo: "directa" },
  { nr: 54, dimension: "OTROS PUNTOS IMPORTANTES", item: "Mi trabajo y los aportes que realizo son valorados y me generan motivación", tipo: "directa" },
  { nr: 55, dimension: "OTROS PUNTOS IMPORTANTES", item: "Me siento libre de culpa cuando no estoy trabajando en algo", tipo: "directa" },
  { nr: 56, dimension: "OTROS PUNTOS IMPORTANTES", item: "En mi trabajo no existen espacios de uso exclusivo de un grupo determinado de personas ligados a un privilegio (p. ej. cafetería exclusiva, baños exclusivos), que cause malestar y perjudique mi ambiente laboral", tipo: "directa" },
  { nr: 57, dimension: "OTROS PUNTOS IMPORTANTES", item: "Puedo dejar de pensar en el trabajo durante mi tiempo libre (pasatiempos, actividades de recreación, otros)", tipo: "directa" },
  { nr: 58, dimension: "OTROS PUNTOS IMPORTANTES", item: "Considero que me encuentro física y mentalmente saludable", tipo: "directa" }
];

// --- NUEVO: helpers de descarga ---
function filenameFromDisposition(dispo?: string, fallback = "documento.bin") {
  if (!dispo) return fallback;
  // Soporta filename*=utf-8''...; filename*=UTF-8''...; y filename="..."
  const m = dispo.match(/filename\*=(?:UTF-8'')?([^;]+)|filename="?([^"]+)"?/i);
  let raw = (m?.[1] || m?.[2] || "").trim();
  try {
    raw = decodeURIComponent(raw);
  } catch { /* si no está bien codificado, seguimos con raw */ }
  raw = raw.replace(/[/\\]+/g, "_");
  return raw || fallback;

}


async function downloadFromStream(documentId: number) {
  try {
    const res = await axiosApi.get(`/api/v1/documents/${documentId}/stream`, { responseType: "blob" });

    const H: any = res?.headers;
    const getHeader = (k: string) =>
      (typeof H?.get === "function" ? H.get(k) : H?.[k]) ||
      (typeof H?.get === "function" ? H.get(k.toLowerCase()) : H?.[k.toLowerCase()]) ||
      undefined;

    const dispo = getHeader("Content-Disposition");
    const ct = getHeader("Content-Type") || "application/octet-stream";
    const ctLower = String(ct).toLowerCase();

    let fallback = "documento.bin";
    if (ctLower.includes("spreadsheetml.sheet")) fallback = "documento.xlsx";
    else if (ctLower.includes("wordprocessingml.document")) fallback = "documento.docx";
    else if (ctLower.includes("pdf")) fallback = "documento.pdf";

    let filename = filenameFromDisposition(dispo, fallback);
    if (!dispo) {
      if (ctLower.includes("spreadsheetml.sheet") && !filename.toLowerCase().endsWith(".xlsx")) filename = filename.replace(/\.[^.]+$/, "") + ".xlsx";
      else if (ctLower.includes("wordprocessingml.document") && !filename.toLowerCase().endsWith(".docx")) filename = filename.replace(/\.[^.]+$/, "") + ".docx";
      else if (ctLower.includes("pdf") && !filename.toLowerCase().endsWith(".pdf")) filename = filename.replace(/\.[^.]+$/, "") + ".pdf";
    }

    const blob = new Blob([res.data], { type: ct });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => window.URL.revokeObjectURL(url), 0);
  } catch (e) {
    throw e;
  }
}



// Helpers: tamaños por Nº de trabajadores
function sizeByDE255(n: number): string {
  if (!Number.isFinite(n) || n < 0) n = 0;
  if (n <= 10) return "1 a 10 (Plan de Prevención)";
  if (n <= 49) return "11 a 49 (Delegado de SST)";
  return "50 o más (Comité Paritario)";
}

function sizeByMiPyme(n: number): string {
  if (!Number.isFinite(n) || n < 0) n = 0;
  if (n <= 9) return "Micro";
  if (n <= 49) return "Pequeña";
  if (n <= 199) return "Mediana";
  return "Grande";
}

type TableColumn = {
  key: string;
  title: string;
  placeholder?: string;
  required?: boolean;
  type?: "text" | "number" | "select";
  options?: Array<string | { label: string; value: string | number }>;
  width?: number;
  readonly?: boolean;              // ← NUEVO
};


type Field = {
  name: string;
  label: string;
  type: "text" | "number" | "date" | "select" | "textarea" | "table";
  required?: boolean;
  options?: string[];
  columns?: TableColumn[];                 // ← usa TableColumn
  minRows?: number;
  addRowText?: string;
  exampleRow?: Record<string, any>;
  // extra meta para cálculos locales (no rompe otros formularios)
  extra?: {
    groupBy?: string;      // p.ej. "dimension"
    scoreKey?: string;     // p.ej. "puntuacion"
  };
};


const COMPANY_SHEET_KEY = (cid: string | number) => `iperc_sheet_company_${cid}`;
const COMPANY_ROWS_KEY = (cid: string | number, sh: string) => `iperc_rows_company_${cid}_${(sh || 'BASE').toUpperCase()}`;

/** --------- Fallbacks mínimos para cuando no hay plantilla cargada --------- */
const DEFAULT_FALLBACK_FIELDS: Field[] = [
  { name: "fecha", label: "Fecha", type: "date", required: true },
  { name: "responsable", label: "Responsable SST", type: "text", required: true },
  { name: "descripcion", label: "Descripción breve", type: "textarea", required: true },
];

const FALLBACK_FIELDS_BY_CODE: Record<string, Field[]> = {
  "RHS-01": [
    { name: "fecha", label: "Fecha del registro", type: "date", required: true },
    { name: "responsable", label: "Responsable SST", type: "text", required: true },
    { name: "observaciones", label: "Observaciones", type: "textarea" },
  ],
  // Agregaremos más códigos según vayas cargando variantes
};

/** --------- Validación local del formulario (no toca backend) --------- */
function validateForm(fields: Field[], form: Record<string, any>) {
  const errors: Record<string, string> = {};

  for (const f of fields) {
    const v = form[f.name];

    if (f.type === "table") {
      const rows = Array.isArray(v) ? v : [];
      const min = (typeof f.minRows === "number" && f.minRows > 0) ? f.minRows : (f.required ? 1 : 0);
      if (min > 0 && rows.length < min) {
        errors[f.name] = `mínimo ${min} fila(s)`;
        continue;
      }

      // PSICO: todas las preguntas deben tener puntuación 1–4
      if (String(f.name).toLowerCase() === "psico_respuestas") {
        const incomplete = rows.some(r => ![1,2,3,4].includes(Number(r?.puntuacion)));
        if (incomplete) {
          errors[f.name] = "complete todas las respuestas (58 ítems con 1–4)";
          continue;
        }
      } else {
        // Genérico: valida columnas requeridas sobre la primera fila como antes
        const reqCols = (f.columns || []).filter(c => c.required).map(c => c.key);
        if (reqCols.length && rows.length) {
          const ok = reqCols.every(k => String(rows[0]?.[k] ?? "").trim() !== "");
          if (!ok) { errors[f.name] = "completar columnas obligatorias"; }
        }
      }
      continue;
    }

    if (f.required && (v === undefined || v === null || String(v).trim() === "")) {
      errors[f.name] = "requerido";
      continue;
    }
    if (f.type === "number" && v !== "" && isNaN(Number(v))) {
      errors[f.name] = "debe ser numérico";
    }
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

function TableField({
  label,
  value,
  onChange,
  columns = [],
  minRows = 0,
  addRowText = "Añadir fila",
  exampleRow = {},
}: {
  label: string;
  value: Array<Record<string, any>>;
  onChange: (rows: Array<Record<string, any>>) => void;
  columns?: TableColumn[];          // ← usa el tipo real
  minRows?: number;
  addRowText?: string;
  exampleRow?: Record<string, any>;
}) {

  const rows = Array.isArray(value) ? value : [];

  const setCell = (rIdx: number, key: string, val: any) => {
    const next = rows.map((r, i) => (i === rIdx ? { ...r, [key]: val } : r));
    onChange(next);
  };


  const addRow = () => onChange([...rows, { ...exampleRow }]);
  const removeRow = (i: number) => onChange(rows.filter((_, idx) => idx !== i));

  // Asegura minRows al montar  
  useEffect(() => {
    if (rows.length < minRows) {
      onChange([...rows, ...Array.from({ length: minRows - rows.length }, () => ({ ...exampleRow }))]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const parseSelectValue = (col: TableColumn | undefined, raw: string) => {
    if (raw === "") return "";  // ← clave para no convertir "" en 0
    const hasNumeric = (col?.options ?? []).some(opt => {
      const v = typeof opt === "string" ? opt : opt.value;
      return typeof v === "number";
    });
    if (hasNumeric) {
      const n = Number(raw);
      return Number.isNaN(n) ? raw : n;
    }
    return raw;
  };


  return (
    <div className="form-group">
      <label className="mb-1 block font-medium text-slate-900 dark:text-slate-100">
        {label}
      </label>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white dark:border-white/10 dark:bg-white/[0.03]">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 dark:bg-white/5">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  style={c.width ? { minWidth: c.width } : undefined}
                  className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700 dark:border-white/10 dark:text-slate-300"
                >
                  {c.title}
                </th>
              ))}
              <th className="border-b border-slate-200 px-3 py-2 w-20 dark:border-white/10"></th>
            </tr>
          </thead>

          <tbody>
            {rows.map((row, rIdx) => (
              <tr key={rIdx} className="align-top">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className="border-b border-slate-200 px-3 py-2 dark:border-white/10"
                  >
                    {c.readonly ? (
                      <div className="px-1 py-1 text-slate-900 dark:text-slate-100">
                        {String(row[c.key] ?? "")}
                      </div>
                    ) : c.type === "select" ? (
                      <select
                        className="w-full input"
                        value={row[c.key] ?? ""}
                        onChange={(e) => setCell(rIdx, c.key, parseSelectValue(c, e.target.value))}
                      >
                        <option value="">Seleccione…</option>
                        {(c.options ?? []).map((opt, i) => {
                          const o = typeof opt === "string" ? { label: opt, value: opt } : opt;
                          return (
                            <option key={i} value={o.value as any}>
                              {o.label}
                            </option>
                          );
                        })}
                      </select>
                    ) : (
                      <input
                        className="w-full input"
                        placeholder={c.placeholder}
                        type={c.type === "number" ? "number" : "text"}
                        value={row[c.key] ?? ""}
                        onChange={(e) =>
                          setCell(
                            rIdx,
                            c.key,
                            c.type === "number"
                              ? (e.target.value === "" ? "" : Number(e.target.value))
                              : e.target.value
                          )
                        }
                      />
                    )}
                  </td>
                ))}

                <td className="border-b border-slate-200 px-3 py-2 text-center dark:border-white/10">
                  {rows.length > (minRows ?? 0) && (
                    <button type="button" className="btn-secondary text-sm" onClick={() => removeRow(rIdx)}>
                      Eliminar
                    </button>
                  )}
                </td>
              </tr>
            ))}

            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={(columns?.length || 0) + 1}
                  className="px-3 py-3 text-slate-500 dark:text-slate-400"
                >
                  Sin filas. Usa “{addRowText}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <button type="button" className="btn-secondary mt-2" onClick={addRow}>
        {addRowText}
      </button>
    </div>
  );
}


export default function DocumentForm() {
  const { id: companyId, code } = useParams();
  const navigate = useNavigate();

  const [tpl, setTpl] = useState<any>(null);
  const [fields, setFields] = useState<Field[]>([]);
  const [form, setForm] = useState<Record<string, any>>({});
  const [missingTpl, setMissingTpl] = useState<boolean>(false);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [priority, setPriority] = useState<{ order?: number; message?: string } | null>(null);

  const [provenance, setProvenance] = useState<Record<string, { source_code?: string; updated_at?: string; value?: any }>>({});
  // Para mostrar el contexto que se autocompleta
  const [ctx, setCtx] = useState<{ activity?: string; risk?: string; workers?: number }>({});
  // PSICO: control multi-trabajador
  const [workerIdx, setWorkerIdx] = useState<number>(1);
  const [maxWorkers, setMaxWorkers] = useState<number>(1);
  const [psicoStore, setPsicoStore] = useState<Record<number, PsicoPack>>({});
  const [showConfirmGen, setShowConfirmGen] = useState(false);
  const [skipPsicoMissingCheck, setSkipPsicoMissingCheck] = useState(false);


  const getData = (r: any) => (r && typeof r === "object" && "data" in r ? r.data : r);

  const [legal, setLegal] = useState<string | null>(null);

  // Fallback de base legal visible en el formulario (no afecta el PDF)
  useEffect(() => {
    if (!legal || String(legal).trim() === "") {
      setLegal("Decreto Ejecutivo 255; Acuerdo MDT-2024-196; Anexos 2 y 3; Código del Trabajo.");
    }
  }, [legal]);

  useEffect(() => {
    (async () => {
      try {
        const companyRes = await api.get(`/api/v1/companies/${companyId}`);
        const company = getData(companyRes);

        // Verificar habilitación de requisito
        try {
          const reqRes = await api.get(`/api/v1/companies/${companyId}/requirements`);
          const reqJson = getData(reqRes);
          const match = reqJson?.items?.find((x: any) => String(x.code).toUpperCase() === String(code).toUpperCase());
          if (match && match.can_generate === false) {
            const msg = match.disabled_reason
              ?? (match.next_due_date
                ? `Cumplido. La próxima generación será el ${new Date(match.next_due_date).toLocaleDateString('es-EC')}.`
                : 'Cumplido. No corresponde generar en este momento.');
            setBlocked(msg);
            return;
          }
          // NUEVO: prioridad y justificación
          if (match?.priority_order || match?.priority_message) {
            setPriority({
              order: match.priority_order,
              message: match.priority_message,
            });
          }

          // base legal
          if (match?.legal) setLegal(match.legal);
        } catch { /* continúa sin bloquear */ }

        const activity = company.actividad ?? company.activity ?? company.sector ?? "";
        const risk = (company.riesgo ?? company.risk_level ?? company.nivel_riesgo ?? company.clasificacion_riesgo ?? "")?.toString().toUpperCase();
        const workers = Number(company.trabajadores ?? company.workers ?? company.numero_trabajadores ?? company.empleados ?? 0);
        setCtx({ activity, risk, workers });
        setMaxWorkers(Number.isFinite(workers) && workers > 0 ? workers : 1);

        // Plantilla segmentada
        const resp = await api.get("/api/v1/templates", { params: { code, activity, risk, workers } });
        const listRaw = getData(resp);
        const list = Array.isArray(listRaw) ? listRaw : (listRaw ? [listRaw] : []);
        const knownRes = await api.get(`/api/v1/companies/${companyId}/known-fields`);
        const payload = getData(knownRes) ?? {};
        const known = (payload && typeof payload === "object" && "known" in payload && payload.known)
          ? payload.known
          : payload; // <- soporte a respuesta plana { razon_social: "...", ... }

        setProvenance(
          (payload && typeof payload === "object" && "provenance" in payload && payload.provenance)
            ? payload.provenance
            : {}
        );

        let ff: Field[] = [];
        let missing = false;
        let t: any = null;

        if (list.length > 0) {
          t = list[0];
          const raw: Field[] = (t.fields ?? t.fields_json ?? []) as Field[];
          if (raw && raw.length > 0) {
            ff = raw;
          } else {
            missing = true;
            ff = (FALLBACK_FIELDS_BY_CODE[String(code).toUpperCase()] ?? DEFAULT_FALLBACK_FIELDS);
          }
          // Si el backend ya adjunta legal en /templates, úsalo como preferente
          if (t?.legal) setLegal(t.legal);
        } else {
          missing = true;
          ff = (FALLBACK_FIELDS_BY_CODE[String(code).toUpperCase()] ?? DEFAULT_FALLBACK_FIELDS);
        }

        setTpl(t);
        setMissingTpl(missing);
        setFields(ff);

        const init: Record<string, any> = {};
        for (const f of ff) {
          const key = f.name;
          if (known[key] !== undefined && known[key] !== null && (Array.isArray(known[key]) || String(known[key]).trim() !== "")) {
            init[key] = known[key];
          } else if (f.type === "table") {
            // si el backend expone defaults.psico_respuestas, úsalo; si no, usa el fallback local
            const D = getTplDefaults(t);
            const defRowsFromTpl = Array.isArray(D?.psico_respuestas) ? D.psico_respuestas : null;
            const defRows = defRowsFromTpl && defRowsFromTpl.length ? defRowsFromTpl : FALLBACK_PSICO_ITEMS;

            if (key === "psico_respuestas" && defRows) {
              init[key] = defRows.map((r: any) => ({
                nr: r.nr,
                dimension: r.dimension,
                item: r.item,
                tipo: r.tipo || "directa",
                puntuacion: "",
                observacion: ""
              }));
            } else {
              const base = Array.isArray(f.exampleRow) ? f.exampleRow[0] : (f.exampleRow || {});
              const m = Number.isFinite(f.minRows) ? Number(f.minRows) : 0;
              init[key] = m > 0 ? Array.from({ length: m }, () => ({ ...base })) : [];
            }
          } else if (key === "actividad") {
            init[key] = activity;
          } else if (key === "riesgo") {
            init[key] = risk;
          } else if (key === "trabajadores") {
            init[key] = Number.isFinite(workers) ? workers : 0;
          } else {
            init[key] = "";
          }
        }

        // aseguras también estos tres por si no están en fields:
        init["actividad"] = init["actividad"] ?? activity ?? "";
        init["riesgo"] = init["riesgo"] ?? risk ?? "";
        init["trabajadores"] = init["trabajadores"] ?? (Number.isFinite(workers) ? workers : 0);

        // Fallback inocuo: completar desde company si known no lo trajo
        if (("razon_social" in init) && (!init["razon_social"] || String(init["razon_social"]).trim() === "")) {
          init["razon_social"] = company.name ?? company.razon_social ?? "";
        }
        if (("ruc" in init) && (!init["ruc"] || String(init["ruc"]).trim() === "")) {
          init["ruc"] = company.ruc ?? "";
        }

        // Autollenar tamaños si los campos existen en la plantilla
        if (ff.some(f => f.name === "tamano_empresa")) {
          init["tamano_empresa"] = sizeByDE255(Number(init["trabajadores"]));
        }
        if (ff.some(f => f.name === "tamano_mipyme")) {
          init["tamano_mipyme"] = sizeByMiPyme(Number(init["trabajadores"]));
        }

        setForm(init);

        // ↓↓↓ NUEVO: lee la hoja y conteo que dejó la sidebar (Guardar Matriz)
        const currentSheet = localStorage.getItem(COMPANY_SHEET_KEY(companyId!)) || "BASE";
        const rowsCountStr = localStorage.getItem(COMPANY_ROWS_KEY(companyId!, currentSheet)) || "";
        setForm(prev => ({
          ...prev,
          sheet: currentSheet,                                  // para que el back filtre correctamente
          rows_count: rowsCountStr ? Number(rowsCountStr) : (prev.rows_count ?? 0),  // para mostrar en el campo
        }));

        // PSICO: pre-cargar cuestionarios guardados (si hay endpoint)
        if (String(code).toUpperCase() === "PSICO-01") {
          try {
            const resList = await api.get(`/api/v1/psico/company/${companyId}`);
            const payload = getData(resList);
            const items = Array.isArray(payload?.items) ? payload.items : [];
            const map: Record<number, PsicoPack> = {};
            for (const it of items) {
              const w = Number(it.worker_index || it.index || it.nr || 0) || 0;
              if (!w) continue;
              map[w] = {
                worker_index: w,
                fields: it.fields ?? {},
                respuestas: Array.isArray(it.respuestas) ? it.respuestas : [],
                completed: isPsicoComplete(it.fields ?? {}, it.respuestas ?? []),
              };
            }
            setPsicoStore(map);
            if (map[1]) {
              setForm({ ...(map[1].fields || {}), psico_respuestas: map[1].respuestas });
            }
          } catch { /* opcional */ }
        }


      } catch (err) {
        console.error(err);
        toast.error("No se pudo cargar la plantilla", { autoClose: 10000 });
      }
    })();
  }, [companyId, code]);

  useEffect(() => {
    if (String(code).toUpperCase() !== "PSICO-01") return;
    const pack = psicoStore[workerIdx];
    if (pack) {
      setForm({ ...(pack.fields || {}), psico_respuestas: pack.respuestas });
    } else {
      const D = getTplDefaults(tpl);
      const defRowsFromTpl = Array.isArray(D?.psico_respuestas) ? D.psico_respuestas : null;
      const baseRows = defRowsFromTpl && defRowsFromTpl.length ? defRowsFromTpl : FALLBACK_PSICO_ITEMS;
      setForm(prev => ({
        ...prev,
        psico_respuestas: baseRows.map((r: any) => ({
          nr: r.nr, dimension: r.dimension, item: r.item,
          tipo: r.tipo || "directa", puntuacion: "", observacion: ""
        }))
      }));
    }
  }, [workerIdx, psicoStore, tpl, code]);


  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);

    try {
      // 1) Gate IPERC-01 (igual que lo tienes)
      if (String(code).toUpperCase() === "IPERC-01") {
        let sheet = (localStorage.getItem(COMPANY_SHEET_KEY(companyId!)) || "BASE")
          .toString()
          .trim()
          .toUpperCase();

        const toArray = (x: any): any[] =>
          Array.isArray(x) ? x
            : Array.isArray(x?.data) ? x.data          // ← arreglo plano en res.data
              : Array.isArray(x?.items) ? x.items
                : Array.isArray(x?.data?.items) ? x.data.items    // ← paginado en res.data.items
                  : [];

        const toTotal = (x: any): number =>
          (typeof x?.data?.total === "number") ? x.data.total
            : (typeof x?.total === "number") ? x.total
              : toArray(x).length;

        let resp = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet, limit: 1, _t: Date.now() } });
        let payload = getData(resp);
        let items = toArray(payload);
        let hasRows = (items.length > 0) || (toTotal(payload) > 0);


        if (!hasRows) {
          const respAll = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet, _t: Date.now() } });
          const arr = toArray(respAll);
          hasRows = arr.length > 0;
          if (hasRows) {
            localStorage.setItem(COMPANY_ROWS_KEY(companyId!, sheet), String(arr.length));
            setForm(prev => ({ ...prev, rows_count: arr.length }));
          }
        }

        if (!hasRows) {
          try {
            const sheetsRes = await api.get(`/api/v1/iperc/company/${companyId}/sheets`);
            const listSheetsRaw = sheetsRes?.data;
            const listSheets = Array.isArray(listSheetsRaw) ? listSheetsRaw : [];

            for (const s of listSheets) {
              const r0 = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet: s, limit: 1, _t: Date.now() } });
              const it0 = toArray(r0);
              if (it0.length > 0) {
                sheet = s.toString().toUpperCase();
                const rAll = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet, _t: Date.now() } });
                const arr = toArray(rAll);
                localStorage.setItem(COMPANY_SHEET_KEY(companyId!), sheet);
                localStorage.setItem(COMPANY_ROWS_KEY(companyId!, sheet), String(arr.length));
                setForm(prev => ({ ...prev, sheet, rows_count: arr.length }));
                hasRows = true;
                break;
              }
            }
          } catch { }
        }

        try {
          const all = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet } });
          const arr = toArray(all);
          localStorage.setItem(COMPANY_ROWS_KEY(companyId!, sheet), String(arr.length));
          setForm(prev => ({ ...prev, rows_count: arr.length }));
        } catch { }

        if (!hasRows) {
          toast.info("Se necesitan datos de la Matriz IPERC (menú izquierdo: IPERC). Guarde la matriz y vuelva a generar.", { autoClose: 10000 });
          return;
        }
      }

      // 2) Validación formulario
      const fieldsForVal = (String(code).toUpperCase() === "PSICO-01")
        ? fields.map(f => f.name === "psico_respuestas" ? ({ ...f, required: false, minRows: 0 }) : f)
        : fields;
      const { valid } = validateForm(fieldsForVal, form);

      if (!valid) {
        toast.warn("Proporcionar información para generar documento", { autoClose: 20000, closeOnClick: true });
        return;
      }

      // 3) Generación + descarga
      const sheetToSend = (form.sheet ?? localStorage.getItem(COMPANY_SHEET_KEY(companyId!)) ?? "BASE").toString();

      // ⚠️ Esta verificación extra solo aplica al documento IPERC-01
      if (String(code).toUpperCase() === "IPERC-01") {
        try {
          const sheetToSendUC = (sheetToSend || "").toString().trim().toUpperCase();
          const chk = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet: sheetToSendUC } });
          const payload = getData(chk);

          const items = Array.isArray(payload?.items) ? payload.items : (Array.isArray(payload) ? payload : []);
          const total = typeof payload?.total === "number" ? payload.total : items.length;

          if (!total || total <= 0) {
            toast.info("No hay filas guardadas en la Matriz IPERC para esta hoja. Guarda al menos una fila y reintenta.", { autoClose: 9000 });
            return;
          }
        } catch (err) {
          console.warn("No se pudo verificar filas IPERC previas; continúo con la generación.", err);
        }
      }


      // === PSICO: aviso si faltan cuestionarios completos ===
      if (String(code).toUpperCase() === "PSICO-01" && !skipPsicoMissingCheck) {
        const respuestas = Array.isArray(form.psico_respuestas) ? form.psico_respuestas : [];
        const thisComplete = isPsicoComplete(form, respuestas);
        const savedComplete = Object.values(psicoStore).filter(p => p?.completed).length;
        const totalComplete = thisComplete
          ? (psicoStore[workerIdx]?.completed ? savedComplete : (savedComplete + 1))
          : savedComplete;

        if (totalComplete < maxWorkers) {
          setShowConfirmGen(true);
          setSubmitting(false);
          return; // se detiene aquí y se muestra el modal
        }
      }


      // ---- PSICO (construimos el arreglo esperado por el backend)
      const genRes = await api.post(`/api/v1/documents/generate`, {
        company_id: Number(companyId),
        template_code: code,
        data: {
          ...form,
          sheet: sheetToSend,
          actividad: form.actividad ?? ctx.activity ?? "",
          riesgo: form.riesgo ?? ctx.risk ?? "",
          trabajadores: Number.isFinite(Number(form.trabajadores)) ? Number(form.trabajadores) : (ctx.workers ?? 0),
        },
      });

      const genData = getData(genRes);
      const docId = Number(genData?.id);


      if (Number.isFinite(docId)) {
        try {
          await downloadFromStream(docId);
          toast.success("Documento generado y descargado");
        } catch {
          toast.info("Documento generado. Abre la pestaña Documentos para descargar.");
        }
      } else {
        toast.info("Documento generado. Abre la pestaña Documentos para descargar.");
      }

      setTimeout(() => navigate(`/companies/${companyId}/documents`), 200);

    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail === "EMPTY_REQUIRED_DATA") {
        toast.error("No hay datos en la Matriz IPERC. Ve a IPERC (menú izquierdo), guarda filas y vuelve a generar.", { autoClose: 12000 });
      } else if (String(detail || "").includes("XLSX template not found")) {
        toast.error("Falta la plantilla XLSX (IPERC-01.xlsx) en el servidor. Contacta al admin para sincronizar plantillas.", { autoClose: 12000 });
      } else {
        toast.error(detail ?? "Error al generar documento");
      }
    } finally {
      setSubmitting(false);
    }
  };



  // Recalcular tamaños al cambiar trabajadores
  useEffect(() => {
    const n = Number(form.trabajadores ?? ctx.workers ?? 0);
    const patch: Record<string, any> = {};

    const hasDE255 = Array.isArray(fields) && fields.some(f => f.name === "tamano_empresa");
    const hasMiPyme = Array.isArray(fields) && fields.some(f => f.name === "tamano_mipyme");

    if (hasDE255) {
      const v = sizeByDE255(n);
      if (form.tamano_empresa !== v) patch.tamano_empresa = v;
    }
    if (hasMiPyme) {
      const v = sizeByMiPyme(n);
      if (form.tamano_mipyme !== v) patch.tamano_mipyme = v;
    }

    if (Object.keys(patch).length) {
      setForm(prev => ({ ...prev, ...patch }));
    }
  }, [form.trabajadores, ctx.workers, fields]);

  // Si el requisito está bloqueado, muestro el mensaje y no sigo
  if (blocked) {
    return (
      <div className="space-y-4">
        <div className="status-banner status-banner-warning text-sm">
          {blocked}
        </div>

        <button className="btn-secondary" type="button" onClick={() => navigate(-1)}>
          ← Volver
        </button>
      </div>
    );
  }

  // Mientras resolvemos template/ctx mostramos un loading simple
  if (!fields.length) {
    return (
      <div className="card">
        <p className="muted">Cargando plantilla…</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="surface space-y-3">
        <div className="section-head flex-wrap">
          <div>
            <span className="page-kicker">Generación documental</span>
            <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
              {tpl ? `${tpl.title}` : `Formulario para ${code}`}
            </h1>
            <p className="page-subtitle">
              {tpl ? `${tpl.activity ?? ctx.activity} · ${tpl.code ?? code}` : `Código ${code}`}
            </p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="metric-card">
            <p className="muted text-sm">Actividad</p>
            <p className="mt-2 font-medium text-slate-900 dark:text-white">{ctx.activity ?? "—"}</p>
          </div>

          <div className="metric-card">
            <p className="muted text-sm">Riesgo</p>
            <p className="mt-2 font-medium text-slate-900 dark:text-white">{ctx.risk ?? "—"}</p>
          </div>

          <div className="metric-card">
            <p className="muted text-sm">Trabajadores</p>
            <p className="mt-2 font-medium text-slate-900 dark:text-white">{ctx.workers ?? 0}</p>
          </div>
        </div>
      </div>

      {missingTpl && (
        <div className="status-banner status-banner-warning text-sm">
          Esta plantilla no tiene estructura cargada en el backend. El formulario está usando un fallback local controlado.
        </div>
      )}

      {priority?.order !== undefined && (
        <div className="status-banner status-banner-info text-sm">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="chip">Prioridad #{priority.order}</span>
            <span>{priority.message ?? "Documento recomendado para iniciar el SGSST."}</span>
          </div>
        </div>
      )}

      {legal && (
        <div className="surface">
          <div className="eyebrow mb-2">Sustento normativo</div>
          <div className="text-sm text-slate-700 dark:text-slate-300">{legal}</div>
        </div>
      )}

      {String(code).toUpperCase() === "PSICO-01" && (
        <div className="surface flex items-center gap-3 flex-wrap">
          <span className="text-sm text-slate-700 dark:text-slate-300">Trabajador:</span>

          <button
            type="button"
            className="btn-secondary"
            onClick={() => setWorkerIdx(i => Math.max(1, i - 1))}
          >
            ◀
          </button>

          <input
            className="w-20 text-center"
            type="number"
            min={1}
            max={maxWorkers}
            value={workerIdx}
            onChange={(e) => {
              let v = Number(e.target.value) || 1;
              if (v < 1) v = 1;
              if (v > maxWorkers) v = maxWorkers;
              setWorkerIdx(v);
            }}
          />

          <span className="text-sm text-slate-700 dark:text-slate-300">de {maxWorkers}</span>

          <button
            type="button"
            className="btn-secondary"
            onClick={() => setWorkerIdx(i => Math.min(maxWorkers, i + 1))}
          >
            ▶
          </button>

          <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
            {psicoStore[workerIdx]?.completed ? "✔ Guardado completo" : "Pendiente"}
          </span>

          <button
            type="button"
            className="btn-ghost ml-auto"
            onClick={() => {
              const pack = psicoStore[workerIdx];
              if (pack) {
                setForm({ ...(pack.fields || {}), psico_respuestas: pack.respuestas });
              } else {
                const D = getTplDefaults(tpl);
                const defRowsFromTpl = Array.isArray(D?.psico_respuestas) ? D.psico_respuestas : null;
                const baseRows = defRowsFromTpl && defRowsFromTpl.length ? defRowsFromTpl : FALLBACK_PSICO_ITEMS;
                setForm(prev => ({
                  ...prev,
                  psico_respuestas: baseRows.map((r: any) => ({
                    nr: r.nr,
                    dimension: r.dimension,
                    item: r.item,
                    tipo: r.tipo || "directa",
                    puntuacion: "",
                    observacion: ""
                  }))
                }));
              }
            }}
          >
            Cargar cuestionario {workerIdx}
          </button>
        </div>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        {fields.map((f) => (
          <div key={f.name} className="form-group">
            <label className="mb-1 block font-medium text-slate-900 dark:text-slate-100">
              {f.label}
              {provenance[f.name] && form[f.name] === provenance[f.name].value && (
                <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
                  (autocompletado de {provenance[f.name].source_code}
                  {" · "}
                  {new Date(provenance[f.name].updated_at as string).toLocaleDateString("es-EC")})
                </span>
              )}
            </label>

            {f.type === "select" ? (
              <select
                className="input"
                required={!!f.required}
                value={form[f.name] ?? ""}
                onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
              >
                <option value="">Seleccione…</option>
                {f.options?.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : f.type === "textarea" ? (
              <textarea
                className="input"
                required={!!f.required}
                value={form[f.name] ?? ""}
                onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
              />
            ) : f.type === "table" ? (
              String(f.name).toLowerCase() === "psico_respuestas" && String(code).toUpperCase() === "PSICO-01" ? (
                <PsicoGrid
                  rows={Array.isArray(form[f.name]) ? form[f.name] : []}
                  onChange={(rows) => setForm({ ...form, [f.name]: rows })}
                />
              ) : (
                <>
                  <TableField
                    label={f.label}
                    value={Array.isArray(form[f.name]) ? form[f.name] : []}
                    onChange={(rows) => setForm({ ...form, [f.name]: rows })}
                    columns={f.columns}
                    minRows={f.minRows}
                    addRowText={f.addRowText}
                    exampleRow={f.exampleRow}
                  />

                  {f.extra?.groupBy && f.extra?.scoreKey && Array.isArray(form[f.name]) && (
                    <div className="mt-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300">
                      {(Object.entries(
                        (form[f.name] as any[]).reduce((acc, r) => {
                          const g = String(r[f.extra!.groupBy!] ?? "").trim() || "—";
                          const s = Number(r[f.extra!.scoreKey!] ?? 0);
                          if (!acc[g]) acc[g] = { n: 0, sum: 0 };
                          if (Number.isFinite(s)) {
                            acc[g].n += 1;
                            acc[g].sum += s;
                          }
                          return acc;
                        }, {} as Record<string, { n: number; sum: number }>)
                      ) as Array<[string, { n: number; sum: number }]>).map(([g, { n, sum }]) => (
                        <div key={g} className="flex items-center justify-between py-1 gap-3 flex-wrap">
                          <span className="font-medium text-slate-900 dark:text-slate-100">{g}</span>
                          <span>{n ? `Suma: ${sum} · Promedio: ${(sum / n).toFixed(2)} (n=${n})` : "—"}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )
            ) : (
              <input
                className="input"
                type={f.type}
                required={!!f.required}
                value={form[f.name] ?? ""}
                onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
              />
            )}
          </div>
        ))}

        <div className="flex gap-2 flex-wrap">
          <button className="btn-primary" type="submit" disabled={submitting}>
            {submitting ? "Generando..." : "Generar"}
          </button>

          {String(code).toUpperCase() === "PSICO-01" && (
            <button
              className="btn-secondary"
              type="button"
              onClick={async () => {
                const respuestas = Array.isArray(form.psico_respuestas) ? form.psico_respuestas : [];
                if (!isPsicoComplete(form, respuestas)) {
                  toast.warn("Completa datos generales y las 58 respuestas (1–4) antes de Guardar.");
                  return;
                }
                const pack: PsicoPack = {
                  worker_index: workerIdx,
                  fields: { ...form, psico_respuestas: undefined },
                  respuestas: respuestas.map((r: any) => ({
                    nr: r.nr,
                    dimension: r.dimension,
                    item: r.item,
                    puntuacion: Number(r.puntuacion),
                    observacion: r.observacion || ""
                  })),
                  completed: true,
                };
                setPsicoStore(prev => ({ ...prev, [workerIdx]: pack }));
                try {
                  await api.post(`/api/v1/psico/company/${companyId}`, pack);
                  toast.success(`Cuestionario del trabajador ${workerIdx} guardado`);
                } catch {
                  toast.info("Guardado local (sin endpoint). Sube luego cuando el API esté listo.");
                }
              }}
            >
              Guardar cuestionario
            </button>
          )}

          <button className="btn-ghost" type="button" onClick={() => navigate(-1)}>
            Cancelar
          </button>
        </div>
      </form>

      {showConfirmGen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 px-4">
          <div className="card w-full max-w-lg space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Faltan cuestionarios
              </h2>
              <p className="muted mt-2 text-sm">
                Aún no se ha completado el número total de cuestionarios ({maxWorkers} trabajadores).
                ¿Deseas generar de todos modos con los cuestionarios disponibles?
              </p>
            </div>

            <div className="flex justify-end gap-2 flex-wrap">
              <button className="btn-secondary" onClick={() => setShowConfirmGen(false)}>
                Cancelar
              </button>

              <button
                className="btn-primary"
                onClick={async () => {
                  setShowConfirmGen(false);
                  setSkipPsicoMissingCheck(true);
                  const ev = new Event("submit", { bubbles: true, cancelable: true });
                  document.querySelector("form")?.dispatchEvent(ev);
                  setTimeout(() => setSkipPsicoMissingCheck(false), 300);
                }}
              >
                Generar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PsicoGrid({
  rows,
  onChange
}: {
  rows: Array<{ nr: number; dimension: string; item: string; puntuacion?: number | ""; observacion?: string }>;
  onChange: (rows: any[]) => void;
}) {
  const setScore = (idx: number, score: number) => {
    const next = rows.map((r, i) => i === idx ? { ...r, puntuacion: score } : r);
    onChange(next);
  };
  // Agrupar por dimensión en el orden en que llegan
  const groups: Array<{ name: string; items: Array<{ idx: number; r: any }> }> = [];
  const byName: Record<string, number> = {};
  rows.forEach((r, idx) => {
    const key = String(r.dimension || "").toUpperCase();
    const gName = r.dimension;
    if (!(key in byName)) {
      byName[key] = groups.length;
      groups.push({ name: gName, items: [] });
    }
    groups[byName[key]].items.push({ idx, r });
  });

  // Sumas por dimensión
  const sums: Record<string, number> = {};
  rows.forEach(r => {
    const g = r.dimension || "—";
    const s = Number(r.puntuacion);
    if (!sums[g]) sums[g] = 0;
    if (Number.isFinite(s)) sums[g] += s;
  });

  return (
    <div className="space-y-4">
      {groups.map((g, gi) => (
        <div
          key={gi}
          className="overflow-x-auto rounded-2xl border border-slate-200 bg-white dark:border-white/10 dark:bg-white/[0.03]"
        >
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-slate-50 dark:bg-white/5">
                <th
                  className="px-3 py-2 text-left font-semibold text-slate-900 dark:text-slate-100"
                  colSpan={6}
                >
                  {g.name}
                </th>
              </tr>

              <tr className="bg-slate-50/70 dark:bg-white/[0.03]">
                <th className="border-b border-slate-200 px-3 py-2 w-12 text-left text-slate-700 dark:border-white/10 dark:text-slate-300">
                  NR
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-700 dark:border-white/10 dark:text-slate-300">
                  Ítem
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-center text-slate-700 dark:border-white/10 dark:text-slate-300">
                  Completamente de Acuerdo (4)
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-center text-slate-700 dark:border-white/10 dark:text-slate-300">
                  Parcialmente de Acuerdo (3)
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-center text-slate-700 dark:border-white/10 dark:text-slate-300">
                  Poco de acuerdo (2)
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-center text-slate-700 dark:border-white/10 dark:text-slate-300">
                  En desacuerdo (1)
                </th>
              </tr>
            </thead>

            <tbody>
              {g.items.map(({ idx, r }) => (
                <tr key={r.nr} className="align-top">
                  <td className="border-b border-slate-200 px-3 py-2 text-slate-900 dark:border-white/10 dark:text-slate-100">
                    {r.nr}
                  </td>
                  <td className="border-b border-slate-200 px-3 py-2 text-slate-900 dark:border-white/10 dark:text-slate-100">
                    {r.item}
                  </td>
                  {[4, 3, 2, 1].map((score) => (
                    <td
                      key={score}
                      className="border-b border-slate-200 px-3 py-2 text-center dark:border-white/10"
                    >
                      <input
                        type="radio"
                        name={`q_${r.nr}`}
                        value={score}
                        checked={Number(r.puntuacion) === score}
                        onChange={() => setScore(idx, score)}
                      />
                    </td>
                  ))}
                </tr>
              ))}

              <tr className="bg-slate-50 dark:bg-white/5">
                <td
                  className="border-t border-slate-200 px-3 py-2 text-right font-semibold text-slate-700 dark:border-white/10 dark:text-slate-200"
                  colSpan={5}
                >
                  Suma de puntos de la dimensión
                </td>
                <td className="border-t border-slate-200 px-3 py-2 text-center font-semibold text-slate-900 dark:border-white/10 dark:text-white">
                  {Number.isFinite(sums[g.name]) ? sums[g.name] : 0}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
