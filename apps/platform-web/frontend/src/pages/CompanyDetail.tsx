import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../app/api";
import RiskButton from "../components/RiskButton";

const enableDocs = (import.meta as any).env?.VITE_ENABLE_DOCS === "1";

type Risk = "BAJO" | "MEDIO" | "ALTO";

type Company = {
  id: number;
  ruc: string;
  nombre?: string;      // ES
  name?: string;        // EN (fallback)
  actividad?: string;   // ES
  activity?: string;    // EN (fallback)
  trabajadores?: number;
  workers?: number;
  riesgo?: Risk;
  risk_level?: Risk;
};

function normalizeCompany(x: any): Required<Pick<Company,"id"|"ruc">> & {
  nombre: string; actividad: string; trabajadores: number; riesgo: Risk;
} {
  return {
    id: x.id,
    ruc: x.ruc,
    nombre: x.nombre ?? x.name ?? "",
    actividad: x.actividad ?? x.activity ?? "",
    trabajadores: (x.trabajadores ?? x.workers ?? 0) as number,
    riesgo: ((x.riesgo ?? x.risk_level) as Risk) ?? "MEDIO",
  };
}


type SstSummary = {
  clasificacion: "MICRO" | "PEQUEÑA" | "MEDIANA" | "GRANDE";
  riesgo: "BAJO" | "MEDIO" | "ALTO";
  responsable_sst: "MONITOR" | "TÉCNICO";
  org_paritario: "NINGUNO" | "DELEGADO" | "COMITÉ";
};

type RequirementItem = {
  code?: string;
  name?: string;
  title?: string;
  exists?: boolean;
  next_due_date?: string | null;
  disabled_reason?: string | null;
};

type UrgentAlert = {
  level: "red" | "yellow";
  title: string;
  dueDate: string;
};

type ComplianceSummary = {
  total: number;
  compliant: number;
  pending: number;
  dueSoon: number;
  expired: number;
  level: "green" | "yellow" | "red" | "neutral";
  compliancePct: number;
  urgent: UrgentAlert[];
};

function dateOnly(value?: string | null): Date | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function formatDate(value?: string | null) {
  const d = dateOnly(value);
  if (!d) return "—";
  return d.toLocaleDateString();
}

function daysBetween(from: Date, to: Date) {
  const ms = to.getTime() - from.getTime();
  return Math.floor(ms / 86400000);
}

function summarizeRequirements(items: RequirementItem[]): ComplianceSummary {
  const today = new Date();
  const todayOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  let compliant = 0;
  let pending = 0;
  let dueSoon = 0;
  let expired = 0;

  const urgent: UrgentAlert[] = [];

  for (const it of items) {
    const due = dateOnly(it.next_due_date);
    const exists = !!it.exists;
    const disabledReason = String(it.disabled_reason ?? "").trim().toUpperCase();

    if (due) {
      const diff = daysBetween(todayOnly, due);

      if (diff < 0) {
        expired += 1;
        urgent.push({
          level: "red",
          title: it.name ?? it.title ?? it.code ?? "Documento",
          dueDate: due.toISOString(),
        });
        continue;
      }

      if (diff <= 30) {
        dueSoon += 1;
        urgent.push({
          level: "yellow",
          title: it.name ?? it.title ?? it.code ?? "Documento",
          dueDate: due.toISOString(),
        });
        continue;
      }

      if (exists || disabledReason.includes("CUMPLIDO")) {
        compliant += 1;
      } else {
        pending += 1;
      }
      continue;
    }

    if (exists || disabledReason.includes("CUMPLIDO")) {
      compliant += 1;
    } else {
      pending += 1;
    }
  }

  const total = items.length;
  const level: ComplianceSummary["level"] =
    expired > 0 ? "red" : dueSoon > 0 ? "yellow" : total > 0 ? "green" : "neutral";

  const compliancePct =
    total > 0 ? Math.round((compliant / total) * 100) : 0;

  urgent.sort((a, b) => {
    const weightA = a.level === "red" ? 0 : 1;
    const weightB = b.level === "red" ? 0 : 1;
    if (weightA !== weightB) return weightA - weightB;
    return new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime();
  });

  return {
    total,
    compliant,
    pending,
    dueSoon,
    expired,
    level,
    compliancePct,
    urgent: urgent.slice(0, 5),
  };
}

function levelUi(level: ComplianceSummary["level"]) {
  if (level === "red") {
    return {
      badge: "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200",
      bar: "bg-red-500",
      label: "Vencido",
    };
  }
  if (level === "yellow") {
    return {
      badge: "border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200",
      bar: "bg-amber-500",
      label: "Próximo a vencer",
    };
  }
  if (level === "green") {
    return {
      badge: "border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200",
      bar: "bg-emerald-500",
      label: "Vigente",
    };
  }
  return {
    badge: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
    bar: "bg-slate-500",
    label: "Sin datos",
  };
}

export default function CompanyDetail() {
  const { id } = useParams();
  const [data, setData] = useState<Company | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [edit, setEdit] = useState(false);
  const [workers, setWorkers] = useState<number>(0);
  const [risk, setRisk] = useState<Company["riesgo"]>("MEDIO");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [sst] = useState<SstSummary | null>(null);
  const [compliance, setCompliance] = useState<ComplianceSummary | null>(null);
  const [complianceLoading, setComplianceLoading] = useState(false);

  useEffect(() => {
  (async () => {
    try {
      const { data } = await api.get(`/api/v1/companies/${id}`);
      const n = normalizeCompany(data);
      setData(n);
      setWorkers(n.trabajadores);
      setRisk(n.riesgo);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? "No se pudo cargar la empresa.");
    }
  })();
}, [id]);

useEffect(() => {
  let active = true;

  (async () => {
    setComplianceLoading(true);
    try {
      const { data } = await api.get(`/api/v1/companies/${id}/requirements`);
      const items = Array.isArray(data?.items) ? data.items : [];
      if (!active) return;
      setCompliance(summarizeRequirements(items));
    } catch {
      if (!active) return;
      setCompliance(null);
    } finally {
      if (active) setComplianceLoading(false);
    }
  })();

  return () => {
    active = false;
  };
}, [id]);


  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const body: any = {};
      if (data && workers !== data.trabajadores) body.trabajadores = workers;
      if (data && risk !== data.riesgo) body.riesgo = risk;

      if (Object.keys(body).length === 0) { setEdit(false); setSaving(false); return; }

      const { data: updated } = await api.put(`/api/v1/companies/${id}`, body);
      const n = normalizeCompany(updated);
      setData(n);
      setWorkers(n.trabajadores);
      setRisk(n.riesgo);
      setEdit(false);
      setMsg("Datos actualizados.");
    } catch (e: any) {
      setMsg(e?.response?.data?.detail ?? "No se pudo actualizar. Verifica tu suscripción y datos.");
    } finally {
      setSaving(false);
    }
  };

  if (err) {
    return (
      <div className="status-banner status-banner-danger text-sm">
        {err}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="card">
        <p className="muted">Cargando…</p>
      </div>
    );
  }

  const complianceUi = levelUi(compliance?.level ?? "neutral");

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">Detalle de empresa</span>
          <h1>{data.nombre}</h1>
          <p className="page-subtitle">
            RUC: {data.ruc} · Actividad: {data.actividad}
          </p>
        </div>

        <div className="flex gap-2 flex-wrap">
          {!edit ? (
            <>
              <button
                onClick={() => setEdit(true)}
                className="btn-primary"
              >
                Actualizar datos
              </button>

              {enableDocs && (
                <Link
                  to={`/companies/${id}/documents`}
                  className="btn-secondary"
                >
                  Documentos
                </Link>
              )}

              <Link to="/companies" className="btn-ghost">
                ← Volver
              </Link>
            </>
          ) : (
            <>
              <button
                onClick={save}
                disabled={saving}
                className="btn-primary disabled:opacity-60"
              >
                {saving ? "Guardando…" : "Listo"}
              </button>

              <button
                onClick={() => {
                  if (data) {
                    setWorkers(data.trabajadores ?? 0);
                    setRisk(data.riesgo ?? "MEDIO");
                  }
                  setMsg(null);
                  setEdit(false);
                }}
                disabled={saving}
                className="btn-secondary disabled:opacity-60"
              >
                Cancelar
              </button>

              <Link to="/companies" className="btn-ghost">
                ← Volver
              </Link>
            </>
          )}
        </div>
      </div>

      {sst && (
        <div className="flex flex-wrap gap-2">
          <span className="chip">
            Clasificación: {sst.clasificacion}
          </span>

          <RiskButton level={sst.riesgo} />

          <span className="chip border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200">
            Responsable: {sst.responsable_sst}
          </span>

          <span className="chip border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200">
            Órgano: {sst.org_paritario}
          </span>
        </div>
      )}

      {msg && (
        <div
          className={`status-banner text-sm ${
            msg.startsWith("No")
              ? "status-banner-danger"
              : "status-banner-success"
          }`}
        >
          {msg}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="metric-card">
          <p className="muted text-sm">RUC</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
            {data.ruc}
          </p>
        </div>

        <div className="metric-card">
          <p className="muted text-sm">Actividad</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
            {data.actividad}
          </p>
        </div>

        <div className="metric-card">
          <p className="muted text-sm">Trabajadores</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">
            {data.trabajadores}
          </p>
        </div>

        <div className="metric-card">
          <p className="muted text-sm">Riesgo actual</p>
          <div className="mt-2">
            <RiskButton level={data?.riesgo ?? risk} />
          </div>
        </div>
      </div>

      <div className="surface space-y-4">
        <div className="section-head flex-wrap">
          <div>
            <h2 className="text-lg">Estado documental</h2>
            <p className="muted mt-1 text-sm">
              Semáforo operativo basado en requisitos y vencimientos.
            </p>
          </div>

          {!complianceLoading && compliance && (
            <span
              className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${complianceUi.badge}`}
            >
              {complianceUi.label}
            </span>
          )}
        </div>

        {complianceLoading && (
          <p className="muted">Cargando estado documental…</p>
        )}

        {!complianceLoading && !compliance && (
          <div className="status-banner status-banner-warning text-sm">
            No se pudo calcular el estado documental de esta empresa.
          </div>
        )}

        {!complianceLoading && compliance && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <div className="metric-card">
                <p className="muted text-sm">Cumplidos</p>
                <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
                  {compliance.compliant}
                </p>
              </div>

              <div className="metric-card">
                <p className="muted text-sm">Pendientes</p>
                <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
                  {compliance.pending}
                </p>
              </div>

              <div className="metric-card border border-amber-200 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10">
                <p className="text-sm text-amber-700 dark:text-amber-200">Próximos</p>
                <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
                  {compliance.dueSoon}
                </p>
              </div>

              <div className="metric-card border border-red-200 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/10">
                <p className="text-sm text-red-700 dark:text-red-200">Vencidos</p>
                <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
                  {compliance.expired}
                </p>
              </div>

              <div className="metric-card">
                <p className="muted text-sm">Cumplimiento</p>
                <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
                  {compliance.compliancePct}%
                </p>
              </div>
            </div>

            <div>
              <p className="muted text-sm mb-2">
                Cumplimiento base: {compliance.compliancePct}%
              </p>

              <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                <div
                  className={`h-3 rounded-full ${complianceUi.bar}`}
                  style={{ width: `${compliance.compliancePct}%` }}
                />
              </div>
            </div>

            {compliance.urgent.length > 0 ? (
              <div className="space-y-2">
                <p className="font-medium text-slate-900 dark:text-white">
                  Alertas prioritarias
                </p>

                {compliance.urgent.map((alert, idx) => (
                  <div
                    key={`${alert.title}-${idx}`}
                    className={`rounded-2xl border px-4 py-3 ${
                      alert.level === "red"
                        ? "border-red-200 bg-red-50 dark:border-red-500/20 dark:bg-red-500/10"
                        : "border-amber-200 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div>
                        <p className="font-medium text-slate-900 dark:text-white">
                          {alert.title}
                        </p>
                      </div>

                      <div className="text-right">
                        <span
                          className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${
                            alert.level === "red"
                              ? "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200"
                              : "border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200"
                          }`}
                        >
                          {alert.level === "red" ? "Vencido" : "Próximo"}
                        </span>

                        <p className="muted mt-2 text-sm">
                          {formatDate(alert.dueDate)}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                No hay alertas críticas en este momento.
              </p>
            )}

            {enableDocs && (
              <div className="pt-1">
                <Link
                  to={`/companies/${id}/documents`}
                  className="btn-secondary"
                >
                  Revisar documentos
                </Link>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="surface">
        <div className="section-head flex-wrap">
          <div>
            <h2 className="text-lg">Matriz de datos</h2>
            <p className="muted mt-1 text-sm">
              Revisa la información base de la empresa y actualiza solo lo necesario.
            </p>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-12 gap-y-6 md:grid-cols-2">
          <div>
            <dt className="muted">RUC</dt>
            <dd className="mt-1 font-medium text-slate-900 dark:text-white">
              {data.ruc}
            </dd>
          </div>

          <div>
            <dt className="muted">Nombre</dt>
            <dd className="mt-1 font-medium text-slate-900 dark:text-white">
              {data.nombre}
            </dd>
          </div>

          <div>
            <dt className="muted">Actividad</dt>
            <dd className="mt-1 font-medium text-slate-900 dark:text-white">
              {data.actividad}
            </dd>
          </div>

          <div>
            <dt className="muted">Trabajadores</dt>
            <dd className="mt-1">
              {!edit ? (
                <span className="font-medium text-slate-900 dark:text-white">
                  {data.trabajadores}
                </span>
              ) : (
                <input
                  type="number"
                  min={0}
                  value={workers}
                  onChange={(e) =>
                    setWorkers(parseInt(e.target.value || "0", 10))
                  }
                  className="w-40"
                />
              )}
            </dd>
          </div>

          <div className="md:col-span-2">
            <dt className="muted">Riesgo</dt>
            <dd className="mt-2">
              {!edit ? (
                <RiskButton level={data?.riesgo ?? risk} />
              ) : (
                <select
                  value={risk}
                  onChange={(e) => setRisk(e.target.value as Company["riesgo"])}
                  className="w-48"
                >
                  <option value="BAJO">BAJO</option>
                  <option value="MEDIO">MEDIO</option>
                  <option value="ALTO">ALTO</option>
                </select>
              )}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
