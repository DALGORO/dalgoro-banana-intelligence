import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/app/api";
import { toast } from "react-toastify";


type Row = {
  id?: number;
  company_id?: number;
  sheet?: string;
  activity?: string;
  process?: string;
  job?: string;
  task?: string;
  hazard_group?: string;
  hazard?: string;
  event?: string;
  consequence?: string;

  // GTC-45
  nd?: number | null;
  ne?: number | null;
  nc?: number | null;
  np?: number | null;
  nr?: number | null;
  risk_interp?: string | null;
  acceptable?: string | null;

  // banderas
  requires_work_permit?: boolean;
  needs_health_surveillance?: boolean;
  needs_env_monitoring?: boolean;
  next_review?: string | null;
  status?: string | null;

  // client-only (edición de fila nueva)
  __isNew?: boolean;
};

const TOOLTIP = {
  process: "Proceso: conjunto de actividades con un objetivo común (ej. Fumigación terrestre).",
  job: "Puesto: cargo/rol que ejecuta la tarea (ej. Fumigador).",
  task: "Tarea: actividad concreta (ej. Mezcla y aplicación de plaguicida).",
  hazard_group: "Grupo de peligro: QUÍMICOS, MECÁNICOS, ERGONÓMICOS, FÍSICOS, ELÉCTRICOS, etc.",
  hazard: "Peligro: fuente o situación con potencial de daño (ej. Exposición a plaguicidas).",
  event: "Evento: forma en que se materializa el peligro (ej. Contacto/inhalación durante aplicación).",
  consequence: "Consecuencia: lesión/daño esperado (ej. Intoxicación aguda).",
  nd: "ND (Nivel de Deficiencia): 0–10 típico GTC-45.",
  ne: "NE (Nivel de Exposición): 0–10 típico GTC-45.",
  nc: "NC (Nivel de Consecuencia): 1–10 típico GTC-45.",
  np: "NP = ND × NE.",
  nr: "NR = NP × NC → clasifica TRIVIAL/TOLERABLE/MODERADO/IMPORTANTE/INTOLERABLE.",
  interp: "Interpretación del riesgo derivada del NR.",
  acceptable: "Aceptabilidad resultante (ACEPTABLE/MEJORAR/NO ACEPTABLE).",
};

export default function IPERCTab() {
  const { id } = useParams();
  const companyId = Number(id);

  const [actividadNormalizada, setActividadNormalizada] = useState<string>("BANANERA");
  const COMPANY_SHEET_KEY = (cid: string|number) => `iperc_sheet_company_${cid}`;
  const COMPANY_ROWS_KEY  = (cid: string|number, sh: string) => `iperc_rows_company_${cid}_${(sh||'BASE').toUpperCase()}`;

  const [sheet, setSheet] = useState<string>(() => {
    // lee último sheet usado
    const key = COMPANY_SHEET_KEY(companyId!);
    return (localStorage.getItem(key) || "BASE").toUpperCase();
  });

  useEffect(() => {
    if (!companyId) return;
    localStorage.setItem(COMPANY_SHEET_KEY(companyId), (sheet || "BASE").toUpperCase());
  }, [companyId, sheet]);

  const [sheets, setSheets] = useState<string[]>(["BASE"]);

  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({ process: "", job: "" });
  const [attemptedSeed, setAttemptedSeed] = useState(false);

  // preset de procesos (para "+ Nuevo")
  const [processList, setProcessList] = useState<string[]>([]);
  const [presetCache, setPresetCache] = useState<Record<string, any>>({});

  // reset de seed al cambiar empresa/hoja
  useEffect(() => { setAttemptedSeed(false); }, [companyId, sheet]);

  // actividad de la empresa
  useEffect(() => {
    (async () => {
      if (!Number.isFinite(companyId) || companyId <= 0) return;
      try {
        const { data } = await api.get(`/api/v1/companies/${companyId}`);
        const act = (data?.actividad || data?.activity || "").toString().trim().toUpperCase();
        setActividadNormalizada(act || "BANANERA");
      } catch { setActividadNormalizada("BANANERA"); }
    })();
  }, [companyId]);

  // cargar hojas existentes
  const loadSheets = useCallback(async () => {
    if (!Number.isFinite(companyId) || companyId <= 0) return;
    try {
      const { data } = await api.get(`/api/v1/iperc/company/${companyId}/sheets`);
      if (Array.isArray(data) && data.length) {
        setSheets(data);
        if (!data.includes(sheet)) setSheet(data[0]);
      } else {
        setSheets(["BASE"]);
        setSheet("BASE");
      }
    } catch { /* no bloquear */ }
  }, [companyId, sheet]);

  useEffect(() => { loadSheets(); }, [loadSheets]);

  // presets de la actividad (lista de procesos)
  const loadProcessList = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/v1/iperc/presets/${actividadNormalizada}/processes`);
      if (Array.isArray(data)) setProcessList(data);
    } catch { /* ignore */ }
  }, [actividadNormalizada]);

  useEffect(() => { loadProcessList(); }, [loadProcessList]);

  const buildUrl = useCallback(() => {
    const base = `/api/v1/iperc/company/${companyId}`;
    const qs = new URLSearchParams();
    qs.set("sheet", sheet);
    if (filters.process.trim()) qs.set("process", filters.process.trim());
    if (filters.job.trim()) qs.set("job", filters.job.trim());
    return `${base}?${qs.toString()}`;
  }, [companyId, filters, sheet]);

  const load = useCallback(async () => {
    if (!Number.isFinite(companyId) || companyId <= 0) return;
    setLoading(true); setError(null);
    try {
      const url = buildUrl();
      const { data } = await api.get(url);
      const arr = Array.isArray(data) ? data : [];
      setRows(arr);

      // Semilla automática por actividad+hoja
      if (arr.length === 0 && !attemptedSeed) {
        setAttemptedSeed(true);
        try {
          await api.post(`/api/v1/iperc/company/${companyId}/seed/${actividadNormalizada}?sheet=${encodeURIComponent(sheet)}`);
          const { data: seeded } = await api.get(url);
          setRows(Array.isArray(seeded) ? seeded : []);
          loadSheets(); // por si crea la hoja
        } catch {/* ignore */}
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "No se pudo cargar la matriz IPERC");
      setRows([]);
    } finally { setLoading(false); }
  }, [companyId, buildUrl, attemptedSeed, actividadNormalizada, sheet, loadSheets]);

  const onGuardarMatriz = async () => {
    try {
      // 1) Verifica que exista al menos una fila guardada en esta empresa+hoja
      const { data } = await api.get(`/api/v1/iperc/company/${companyId}`, {
        params: { sheet, limit: 1 },
      });
      const items = Array.isArray((data as any)?.items) ? (data as any).items
                  : (Array.isArray(data) ? data : []);
      if (!items.length) {
        toast.info("No hay filas guardadas en esta hoja. Guarde al menos una fila y reintente.", { autoClose: 8000 });
        return;
      }

      // 2) Obtiene el total (si no tienes endpoint de conteo, pide sin limit)
      const { data: all } = await api.get(`/api/v1/iperc/company/${companyId}`, { params: { sheet } });
      const arr = Array.isArray((all as any)?.items) ? (all as any).items
                : (Array.isArray(all) ? all : []);
      const total = arr.length;

      // 3) Persiste el sheet y el total en localStorage
      localStorage.setItem(COMPANY_SHEET_KEY(companyId!), (sheet || "BASE").toUpperCase());
      localStorage.setItem(COMPANY_ROWS_KEY(companyId!, sheet || "BASE"), String(total));

      toast.success(`Matriz verificada y guardada (${total} fila(s))`, { autoClose: 5000 });
    } catch (e) {
      console.error(e);
      toast.error("No se pudo verificar/guardar la matriz", { autoClose: 8000 });
    }
  };

  useEffect(() => { load(); }, [load]);

  // cálculo local (GTC-45)
  const calcLocal = (nd?: number|null, ne?: number|null, nc?: number|null) => {
    if (nd == null || ne == null || nc == null) return { np: null, nr: null, npLevel: "", nrLevel: "" };
    const np = Number(nd) * Number(ne);
    let npLevel = "";
    if (24 <= np && np <= 40) npLevel = "MA";
    else if (10 <= np && np <= 20) npLevel = "A";
    else if ( 6 <= np && np <=  8) npLevel = "M";
    else npLevel = "B"; // 2–4

    const nr = np * Number(nc);
    let nrLevel = "IV"; // =20
    if (nr >= 600) nrLevel = "I";
    else if (nr >= 150) nrLevel = "II";
    else if (nr >= 40) nrLevel = "III";

    return { np, nr, npLevel, nrLevel };
  };

  const ND_OPTIONS = [
    { v: 10, label: "Muy Alto (MA)" },
    { v: 6,  label: "Alto (A)" },
    { v: 2,  label: "Medio (M)" },
  ];
  const NE_OPTIONS = [
    { v: 4, label: "Continua (EC)" },
    { v: 3, label: "Frecuente (EF)" },
    { v: 2, label: "Ocasional (EO)" },
    { v: 1, label: "Esporádica (EE)" },
  ];
  const NC_OPTIONS = [
    { v: 100, label: "Mortal/Catastrófico (M)" },
    { v: 60,  label: "Muy grave (MG)" },
    { v: 25,  label: "Grave (G)" },
    { v: 10,  label: "Leve (L)" },
  ];

  const onSave = async (row: Row) => {
    if (!row) return;
    try {
      setLoading(true);
      const payload = { ...row, sheet, activity: actividadNormalizada };
      if (row.id) {
        const { data } = await api.put(`/api/v1/iperc/${row.id}`, payload);
        setRows(prev => prev.map(r => (r.id === row.id ? data : r)));
      } else {
        const body = [{ ...payload, company_id: companyId }];
        const { data } = await api.post(`/api/v1/iperc/company/${companyId}`, body);
        setRows(prev => [...data, ...prev].map(x => ({...x, __isNew: false})));
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "No se pudo guardar el registro");
    } finally { setLoading(false); }
  };

  const onDelete = async (row: Row) => {
    if (!row?.id) {
      // si es nueva sin guardar, simplemente quítala
      setRows(prev => prev.filter(r => r !== row));
      return;
    }
    try {
      setLoading(true);
      await api.delete(`/api/v1/iperc/${row.id}`);
      setRows(prev => prev.filter(r => r.id !== row.id));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "No se pudo eliminar el registro");
    } finally { setLoading(false); }
  };

  const fetchProcessDefaults = async (name: string) => {
    const key = `${actividadNormalizada}::${name}`;
    if (presetCache[key]) return presetCache[key];
    try {
      const { data } = await api.get(`/api/v1/iperc/presets/${actividadNormalizada}/process`, { params: { name } });
      setPresetCache(prev => ({ ...prev, [key]: data || {} }));
      return data || {};
    } catch {
      setPresetCache(prev => ({ ...prev, [key]: {} }));
      return {};
    }
  };

  const addNewRow = () => {
    setRows(prev => [
      {
        __isNew: true,
        company_id: companyId,
        sheet,
        activity: actividadNormalizada,
        process: "",
        job: "",
        task: "",
        hazard_group: "",
        hazard: "",
        event: "",
        consequence: "",
        nd: null, ne: null, nc: null,
        np: null, nr: null, risk_interp: "", acceptable: "",
        requires_work_permit: false,
        needs_health_surveillance: false,
        needs_env_monitoring: false,
        next_review: null,
        status: "vigente",
      },
      ...prev,
    ]);
  };

  return (
    <div className="p-4">
      <h1 className="text-xl font-semibold mb-4">Matriz IPERC</h1>

      {/* Hoja/versión */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <label className="text-sm opacity-75">Hoja:</label>
        <select className="input" value={sheet} onChange={e => setSheet(e.target.value)}>
          {sheets.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          className="btn-secondary"
          onClick={() => {
            const name = prompt("Nombre de la nueva hoja:", "2025");
            if (!name) return;
            const up = name.toUpperCase();
            setSheet(up);
            setSheets(prev => Array.from(new Set([up, ...prev])));
            setRows([]); setAttemptedSeed(false);
          }}
        >
          + Hoja
        </button>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <input
          className="input"
          placeholder="Filtrar por Proceso"
          value={filters.process}
          onChange={e => setFilters(f => ({ ...f, process: e.target.value }))}
        />
        <input
          className="input"
          placeholder="Filtrar por Puesto"
          value={filters.job}
          onChange={e => setFilters(f => ({ ...f, job: e.target.value }))}
        />
        <button className="btn-primary" onClick={load} disabled={loading || !Number.isFinite(companyId)}>
          {loading ? "Cargando..." : "Actualizar"}
        </button>

        <button className="btn" onClick={onGuardarMatriz} disabled={!Number.isFinite(companyId)}>
          Guardar Matriz
        </button>  {/* ← NUEVO BOTÓN */}

        <button className="btn-secondary" onClick={addNewRow} disabled={!Number.isFinite(companyId)}>
          + Nuevo
        </button>

      </div>

      {error && <div className="mb-4 text-sm text-red-500">{error}</div>}

      {/* Tabla */}
      <div className="overflow-auto">
        <table className="table w-full iperc-grid">
          <thead>
            <tr>
              <th title={TOOLTIP.process}>Proceso</th>
              <th title={TOOLTIP.job}>Puesto</th>
              <th title={TOOLTIP.task}>Tarea</th>
              <th title={TOOLTIP.hazard_group}>Grupo</th>
              <th title={TOOLTIP.hazard}>Peligro</th>
              <th title={TOOLTIP.event}>Evento</th>
              <th title={TOOLTIP.consequence}>Consecuencia</th>

              <th title={TOOLTIP.nd}>ND</th>
              <th title={TOOLTIP.ne}>NE</th>
              <th title={TOOLTIP.np}>NP</th>
              <th title={TOOLTIP.nc}>NC</th>
              <th title={TOOLTIP.nr}>NR</th>
              <th title={TOOLTIP.interp}>Interpretación</th>
              <th title={TOOLTIP.acceptable}>Aceptabilidad</th>

              <th>Flags</th>
              <th>Próx. Revisión</th>
              <th className="w-44"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const live = calcLocal(r.nd, r.ne, r.nc);
              const np = live.np ?? r.np ?? "";
              const nr = live.nr ?? r.nr ?? "";

              const renderProcessCell = () => {
                if (!r.__isNew) return r.process;
                return (
                  <select
                    className="input min-w-[220px]"
                    value={r.process || ""}
                    onChange={async (e) => {
                      const name = e.target.value;
                      const defs = name ? await fetchProcessDefaults(name) : {};
                      setRows(prev => prev.map((x,ix) => {
                        if (ix !== i) return x;
                        return {
                          ...x,
                          process: name,
                          job: defs?.defaults?.job ?? "",
                          task: defs?.defaults?.task ?? "",
                          hazard_group: defs?.defaults?.hazard_group ?? "",
                          hazard: defs?.defaults?.hazard ?? "",
                          event: defs?.defaults?.event ?? "",
                          consequence: defs?.defaults?.consequence ?? "",
                          // ND/NE/NC los llena usuario
                        };
                      }));
                    }}
                  >
                    <option value="">— Seleccionar —</option>
                    {processList.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                );
              };

              const renderText = (val?: string) => <span className="whitespace-pre-wrap">{val || ""}</span>;

              return (
                <tr key={r.id ?? `tmp-${i}`}>
                  <td>{renderProcessCell()}</td>
                  <td>{renderText(r.job)}</td>
                  <td>{renderText(r.task)}</td>
                  <td>{renderText(r.hazard_group)}</td>
                  <td>{renderText(r.hazard)}</td>
                  <td>{renderText(r.event)}</td>
                  <td>{renderText(r.consequence)}</td>

                  <td>
                    <select className="input w-44" value={r.nd ?? ""} 
                            onChange={e=>setRows(prev=>prev.map((x,ix)=>ix===i?{...x, nd: e.target.value===""?null:Number(e.target.value)}:x))}>
                      <option value="">ND…</option>
                      {ND_OPTIONS.map(o=><option key={o.v} value={o.v}>{o.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <select className="input w-44" value={r.ne ?? ""} 
                            onChange={e=>setRows(prev=>prev.map((x,ix)=>ix===i?{...x, ne: e.target.value===""?null:Number(e.target.value)}:x))}>
                      <option value="">NE…</option>
                      {NE_OPTIONS.map(o=><option key={o.v} value={o.v}>{o.label}</option>)}
                    </select>
                  </td>
                  <td>{np}</td>
                  <td>
                    <select className="input w-44" value={r.nc ?? ""} 
                            onChange={e=>setRows(prev=>prev.map((x,ix)=>ix===i?{...x, nc: e.target.value===""?null:Number(e.target.value)}:x))}>
                      <option value="">NC…</option>
                      {NC_OPTIONS.map(o=><option key={o.v} value={o.v}>{o.label}</option>)}
                    </select>
                  </td>
                  <td>{nr}</td>
                  <td>{live.nrLevel ? `NR ${live.nrLevel}` : ""}</td>
                  <td>{live.nrLevel ? (live.nrLevel==="I"?"NO ACEPTABLE": live.nrLevel==="II"?"NO ACEPTABLE": live.nrLevel==="III"?"MEJORAR":"ACEPTABLE") : ""}</td>
                  
                  <td>
                    {r.requires_work_permit && "PT "}
                    {r.needs_health_surveillance && "VigSal "}
                    {r.needs_env_monitoring && "Mon "}
                  </td>
                  <td>{r.next_review ?? ""}</td>
                  <td className="flex gap-2">
                    {r.__isNew ? (
                      <>
                        <button className="btn-primary" onClick={() => onSave(r)}>Guardar</button>
                        <button className="btn-danger" onClick={() => onDelete(r)}>Cancelar</button>
                      </>
                    ) : (
                      <>
                        <button className="btn-secondary" onClick={() => onSave(r)}>Guardar</button>
                        {r.id && <button className="btn-danger" onClick={() => onDelete(r)}>Eliminar</button>}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={17} className="text-center py-6 text-sm opacity-70">
                  No hay registros IPERC para esta empresa/hoja.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
