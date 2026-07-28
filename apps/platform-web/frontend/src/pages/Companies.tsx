import { useEffect, useState } from "react";
import { api } from "../app/api";
import { Link, useNavigate } from "react-router-dom";
import CompanyFormModal from "../components/CompanyFormModal";
import SuccessModal from "../components/SuccessModal";
import CompanyEditModal from "../components/CompanyEditModal";

type Flags = { payment_required: boolean };

type SubscriptionStatus = {
  plan: string;
  status: string;
  free_trial_until?: string | null;
  current_period_end?: string | null;
  companies_quota: number;
  days_left?: number | null;
};

type RequirementItem = {
  code?: string;
  name?: string;
  title?: string;
  exists?: boolean;
  next_due_date?: string | null;
  disabled_reason?: string | null;
};

type CompanyCompliance = {
  total: number;
  compliant: number;
  pending: number;
  dueSoon: number;
  expired: number;
  level: "green" | "yellow" | "red" | "neutral";
  compliancePct: number;
};

function dateOnly(value?: string | null): Date | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function daysBetween(from: Date, to: Date) {
  const ms = to.getTime() - from.getTime();
  return Math.floor(ms / 86400000);
}

function summarizeRequirements(items: RequirementItem[]): CompanyCompliance {
  const today = new Date();
  const todayOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  let compliant = 0;
  let pending = 0;
  let dueSoon = 0;
  let expired = 0;

  for (const it of items) {
    const due = dateOnly(it.next_due_date);
    const exists = !!it.exists;
    const disabledReason = String(it.disabled_reason ?? "").trim().toUpperCase();

    if (due) {
      const diff = daysBetween(todayOnly, due);

      if (diff < 0) {
        expired += 1;
        continue;
      }

      if (diff <= 30) {
        dueSoon += 1;
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
  const level: CompanyCompliance["level"] =
    expired > 0 ? "red" : dueSoon > 0 ? "yellow" : total > 0 ? "green" : "neutral";

  const compliancePct =
    total > 0 ? Math.round((compliant / total) * 100) : 0;

  return {
    total,
    compliant,
    pending,
    dueSoon,
    expired,
    level,
    compliancePct,
  };
}

function levelUi(level: CompanyCompliance["level"]) {
  if (level === "red") {
    return {
      badge: "border border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-200",
      bar: "bg-red-500",
      track: "bg-slate-200 dark:bg-slate-800",
      label: "Vencido",
    };
  }

  if (level === "yellow") {
    return {
      badge: "border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-200",
      bar: "bg-amber-500",
      track: "bg-slate-200 dark:bg-slate-800",
      label: "Próximo a vencer",
    };
  }

  if (level === "green") {
    return {
      badge: "border border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
      bar: "bg-emerald-500",
      track: "bg-slate-200 dark:bg-slate-800",
      label: "Vigente",
    };
  }

  return {
    badge: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
    bar: "bg-slate-500",
    track: "bg-slate-200 dark:bg-slate-800",
    label: "Sin datos",
  };
}

const enableDocs = (import.meta as any).env?.VITE_ENABLE_DOCS === "1";

type Company = {
  id: number;
  ruc: string;
  nombre?: string;           // alias ES desde el backend
  name?: string;             // fallback EN
  actividad?: string;        // para pre-cargar prompts
  trabajadores?: number;     // "
  riesgo?: "BAJO" | "MEDIO" | "ALTO" | string; // "
};

function normalizePlan(value?: string | null) {
  return String(value ?? "").trim().toUpperCase().replace(/[-\s]+/g, "_");
}

function normalizeStatus(value?: string | null) {
  return String(value ?? "").trim().toUpperCase().replace(/[-\s]+/g, "_");
}

function isSubscriptionBlocked(sub: SubscriptionStatus | null) {
  if (!sub) return false;

  const plan = normalizePlan(sub.plan);
  const status = normalizeStatus(sub.status);

  if (status === "PAST_DUE" || status === "CANCELED") {
    return true;
  }

  if ((plan === "FREE_TRIAL" || plan === "TRIAL") && sub.free_trial_until) {
    const end = new Date(sub.free_trial_until);
    if (!Number.isNaN(end.getTime()) && end.getTime() < Date.now()) {
      return true;
    }
  }

  return false;
}

export default function Companies(){
  const navigate = useNavigate();
  const [openForm, setOpenForm] = useState(false);
  const [openOk, setOpenOk] = useState(false);
  const [items, setItems] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string|undefined>();
  const [isAdmin, setIsAdmin] = useState(false);
  const [openEdit, setOpenEdit] = useState(false);       // ← NUEVO
  const [edit, setEdit] = useState<Company | null>(null); // ← NUEVO

  const [flags, setFlags] = useState<Flags | null>(null);
  const [subStatus, setSubStatus] = useState<SubscriptionStatus | null>(null);
  const [complianceMap, setComplianceMap] = useState<Record<number, CompanyCompliance>>({});
  const maxCompanies = isAdmin
    ? null
    : (typeof subStatus?.companies_quota === "number" ? subStatus.companies_quota : null);

  const atQuota = maxCompanies !== null && items.length >= maxCompanies;

  const remainingCompanies =
    maxCompanies !== null ? Math.max(maxCompanies - items.length, 0) : null;

  const quotaText = isAdmin
    ? "ADMIN sin límite de empresas."
    : maxCompanies === null
      ? "Cupo pendiente de sincronizar. El backend mantiene la validación final."
      : `Cupo usado: ${items.length}/${maxCompanies} · disponibles: ${remainingCompanies}`;

  const subscriptionBlocked = isSubscriptionBlocked(subStatus);
  const disableCreate = !subscriptionBlocked && atQuota;

  const goToPay = () => {
    const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    try {
      sessionStorage.setItem("post_billing_redirect", currentPath || "/companies");
    } catch {}
    navigate("/pay");
  };

  function handleCreated(c: any) {
    setItems(prev => [c, ...prev]); // inyecta sin recargar
    setOpenOk(true);                 // abre confirmación éxito
  }
  
  useEffect(() => {
    let active = true;

    (async () => {
      try {
        const { data } = await api.get("/api/v1/companies");
        if (active) setItems(data);
      } catch (e: any) {
        if (active) setErr(e?.response?.data?.detail ?? "Error al cargar empresas");
      } finally {
        if (active) setLoading(false);
      }

      try {
        const me = await api.get("/api/v1/auth/me");
        if (active) {
          setIsAdmin(Array.isArray(me.data?.roles) && me.data.roles.includes("ADMIN"));
        }
      } catch {
        if (active) setIsAdmin(false);
      }

      try {
        const { data: f } = await api.get("/api/v1/system/flags");
        if (active) setFlags(f);
      } catch {
        if (active) setFlags(null);
      }

      try {
        const { data: s } = await api.get("/api/v1/subscriptions/status");
        if (active) setSubStatus(s);
      } catch {
        if (active) setSubStatus(null);
      }
    })();

    return () => {
      active = false;
    };
  }, []);
  
  useEffect(() => {
    let active = true;

    const loadCompliance = async () => {
      if (!items.length) {
        setComplianceMap({});
        return;
      }

      try {
        const entries = await Promise.all(
          items.map(async (company: any) => {
            try {
              const { data } = await api.get(`/api/v1/companies/${company.id}/requirements`);
              const reqItems = Array.isArray(data?.items) ? data.items : [];
              return [company.id, summarizeRequirements(reqItems)] as const;
            } catch {
              return [
                company.id,
                {
                  total: 0,
                  compliant: 0,
                  pending: 0,
                  dueSoon: 0,
                  expired: 0,
                  level: "neutral" as const,
                  compliancePct: 0,
                },
              ] as const;
            }
          })
        );

        if (!active) return;
        setComplianceMap(Object.fromEntries(entries));
      } catch {
        if (!active) return;
        setComplianceMap({});
      }
    };

    loadCompliance();

    return () => {
      active = false;
    };
  }, [items]);
    
  return (
    <div className="card">      
      <div className="flex justify-between items-start mb-4">
        <div>
          <h1>Empresas</h1>
          <p className="muted text-sm mt-1">{quotaText}</p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              onClick={async () => {
                const v = !(flags?.payment_required);
                await api.patch("/api/v1/system/flags/payment-required", { value: v });
                const { data: f } = await api.get("/api/v1/system/flags");
                setFlags(f);
                alert(`Pago ${f.payment_required ? "ACTIVADO" : "DESACTIVADO"}`);
              }}
              className="btn-secondary rounded-full"
              title="Alternar requisito de pago (solo ADMIN)"
            >
              {flags?.payment_required ? "Desactivar pago" : "Activar pago"}
            </button>
          )}

          <button
            onClick={() => {
              if (subscriptionBlocked) {
                goToPay();
                return;
              }

              if (!atQuota) {
                setOpenForm(true);
              }
            }}
            disabled={disableCreate}
            className={`rounded-full ${
              disableCreate
                ? "btn-secondary opacity-60 cursor-not-allowed"
                : "btn-primary"
            }`}
            title={
              subscriptionBlocked
                ? "Tu suscripción está vencida o inactiva. Haz clic para renovarla."
                : atQuota
                ? `Cupo alcanzado (${items.length}/${maxCompanies})`
                : "Crear nueva empresa"
            }
          >
            {subscriptionBlocked ? "Renovar suscripción" : "Nueva empresa"}
          </button>
        </div>
      </div>

      {subscriptionBlocked && (
        <div className="status-banner status-banner-warning mb-4 text-sm">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              Tu suscripción está vencida o inactiva. Puedes seguir revisando empresas registradas, pero para crear nuevas empresas o recuperar el acceso completo debes renovarla.
            </div>
            <button className="btn-primary rounded-full" onClick={goToPay}>
              Ir a renovación
            </button>
          </div>
        </div>
      )}

      {loading && <div className="muted">Cargando…</div>}
      {err && (
        <div className="status-banner status-banner-danger text-sm">
          {err}
        </div>
      )}

      {!loading && !err && (
        <>
          <ul className="space-y-4">
            {items.map((e) => (
              <li key={e.id}>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.03]">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    {/* Bloque izquierdo */}
                    <div className="min-w-0 flex-1">
                      <Link
                        to={`/companies/${e.id}`}
                        className="text-base font-semibold text-slate-900 hover:underline dark:text-white"
                      >
                        {e.nombre ?? (e as any).name ?? "(sin nombre)"}
                      </Link>

                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
                        {e.ruc && <span>RUC: {e.ruc}</span>}
                        {e.actividad && <span>Actividad: {e.actividad}</span>}
                        {(e.trabajadores ?? 0) > 0 && <span>{e.trabajadores} trabajadores</span>}
                      </div>

                      {(() => {
                        const compliance = complianceMap[e.id];
                        if (!compliance) return null;

                        const ui = levelUi(compliance.level);

                        return (
                          <div className="mt-4 space-y-3">
                            <div className="flex items-center justify-between gap-2 flex-wrap">
                              <span
                                className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${ui.badge}`}
                              >
                                {ui.label}
                              </span>

                              <span className="text-xs text-slate-500 dark:text-slate-300">
                                Cumplimiento base: {compliance.compliancePct}%
                              </span>
                            </div>

                            <div className={`h-2 w-full overflow-hidden rounded-full ${ui.track}`}>
                              <div
                                className={`h-2 rounded-full ${ui.bar}`}
                                style={{ width: `${compliance.compliancePct}%` }}
                              />
                            </div>

                            <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                              <div>
                                <span className="text-slate-500 dark:text-slate-400">Cumplidos</span>
                                <div className="font-medium text-slate-900 dark:text-white">
                                  {compliance.compliant}
                                </div>
                              </div>

                              <div>
                                <span className="text-slate-500 dark:text-slate-400">Pendientes</span>
                                <div className="font-medium text-slate-900 dark:text-white">
                                  {compliance.pending}
                                </div>
                              </div>

                              <div>
                                <span className="text-slate-500 dark:text-slate-400">Próximos</span>
                                <div className="font-medium text-slate-900 dark:text-white">
                                  {compliance.dueSoon}
                                </div>
                              </div>

                              <div>
                                <span className="text-slate-500 dark:text-slate-400">Vencidos</span>
                                <div className="font-medium text-slate-900 dark:text-white">
                                  {compliance.expired}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                    </div>

                    {/* Bloque derecho */}
                    <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                      <Link
                        to={`/companies/${e.id}`}
                        className="btn-secondary rounded-full"
                      >
                        Ver
                      </Link>

                      {isAdmin && (
                        <button
                          onClick={() => {
                            setEdit(e);
                            setOpenEdit(true);
                          }}
                          className="btn-secondary rounded-full"
                          title="Editar datos de empresa (ADMIN)"
                        >
                          Editar
                        </button>
                      )}

                      {enableDocs && (
                        <Link
                          to={`/companies/${e.id}/documents`}
                          className="btn-primary rounded-full"
                        >
                          Documentos
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}

            {items.length === 0 && (
              <li className="empty-state">
                <div className="text-base font-medium text-slate-900 dark:text-white">
                  Todavía no has registrado empresas.
                </div>
                <div className="muted mt-2">
                  El siguiente paso recomendado es crear la primera empresa para habilitar el flujo documental y el seguimiento de cumplimiento.
                </div>
              </li>
            )}
          </ul>


          {/*  Modales FUERA del map  */}
          <CompanyFormModal
            open={openForm}
            onClose={() => setOpenForm(false)}
            onSuccess={handleCreated}
            quotaBlocked={atQuota}
            quotaText={quotaText}
          />

          <SuccessModal
            open={openOk}
            onClose={() => setOpenOk(false)}
            message="La empresa se registró correctamente."
          />
          <CompanyEditModal
            open={openEdit}
            company={edit}
            onClose={() => { setOpenEdit(false); setEdit(null); }}
            onSaved={(updated) => {
              setItems(prev => prev.map(x => x.id === updated.id ? { ...x, ...updated } : x));
              setOpenEdit(false);
              setEdit(null);
            }}
          />
        </>
      )}
    </div>
  );
}
