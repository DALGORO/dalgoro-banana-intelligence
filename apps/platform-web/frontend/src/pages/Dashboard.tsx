import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../app/api";
import WelcomeOverlay from "../components/WelcomeOverlay";

type Company = {
  id: number;
  nombre?: string;
  name?: string;
  actividad?: string;
  activity?: string;
};

type RequirementItem = {
  code?: string;
  name?: string;
  title?: string;
  exists?: boolean;
  next_due_date?: string | null;
  can_generate?: boolean;
  disabled_reason?: string | null;
};

type UrgentAlert = {
  level: "red" | "yellow";
  title: string;
  dueDate: string;
};

type CompanyHealth = {
  id: number;
  name: string;
  activity: string;
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

function companyName(c: Company) {
  return c.nombre ?? c.name ?? `Empresa ${c.id}`;
}

function companyActivity(c: Company) {
  return c.actividad ?? c.activity ?? "Actividad no definida";
}

function summarizeCompany(company: Company, items: RequirementItem[]): CompanyHealth {
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
  const level: CompanyHealth["level"] =
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
    id: company.id,
    name: companyName(company),
    activity: companyActivity(company),
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

function levelStyles(level: CompanyHealth["level"]) {
  if (level === "red") {
    return {
      card: "border border-red-200 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/10",
      chip: "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200",
      track: "bg-slate-200 dark:bg-slate-800",
      bar: "bg-red-500",
      label: "Vencido",
    };
  }

  if (level === "yellow") {
    return {
      card: "border border-amber-200 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10",
      chip: "border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200",
      track: "bg-slate-200 dark:bg-slate-800",
      bar: "bg-amber-500",
      label: "Próximo a vencer",
    };
  }

  if (level === "green") {
    return {
      card: "border border-emerald-200 bg-emerald-50/80 dark:border-emerald-500/20 dark:bg-emerald-500/10",
      chip: "border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200",
      track: "bg-slate-200 dark:bg-slate-800",
      bar: "bg-emerald-500",
      label: "Vigente",
    };
  }

  return {
    card: "border border-slate-200 bg-white dark:border-white/10 dark:bg-white/[0.03]",
    chip: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
    track: "bg-slate-200 dark:bg-slate-800",
    bar: "bg-slate-500",
    label: "Sin datos",
  };
}

function GaugeCard({
  title,
  value,
  subtitle,
  percent,
  tone = "slate",
}: {
  title: string;
  value: string | number;
  subtitle: string;
  percent: number;
  tone?: "emerald" | "amber" | "red" | "slate";
}) {
  const safePercent = Math.max(0, Math.min(100, percent));
  const angle = (safePercent / 100) * 360;

  const toneMap = {
    emerald: {
      ring: "#10b981",
      soft: "border-emerald-200 bg-emerald-50/80 dark:border-emerald-500/20 dark:bg-emerald-500/10",
      text: "text-emerald-700 dark:text-emerald-200",
      center: "bg-white text-slate-700 dark:bg-[#192B2F] dark:text-slate-200",
    },
    amber: {
      ring: "#f59e0b",
      soft: "border-amber-200 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10",
      text: "text-amber-700 dark:text-amber-200",
      center: "bg-white text-slate-700 dark:bg-[#192B2F] dark:text-slate-200",
    },
    red: {
      ring: "#ef4444",
      soft: "border-red-200 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/10",
      text: "text-red-700 dark:text-red-200",
      center: "bg-white text-slate-700 dark:bg-[#192B2F] dark:text-slate-200",
    },
    slate: {
      ring: "#94a3b8",
      soft: "border-slate-200 bg-white dark:border-white/10 dark:bg-white/[0.03]",
      text: "text-slate-700 dark:text-slate-200",
      center: "bg-white text-slate-700 dark:bg-[#192B2F] dark:text-slate-200",
    },
  } as const;

  const ui = toneMap[tone];

  return (
    <div className={`metric-card ${ui.soft}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-slate-900 dark:text-white">{title}</h2>
          <p className="muted mt-2">{subtitle}</p>
        </div>

        <div
          className="relative w-20 h-20 rounded-full flex items-center justify-center"
          style={{
            background: `conic-gradient(${ui.ring} ${angle}deg, rgba(148,163,184,0.18) ${angle}deg 360deg)`,
          }}
        >
          <div
            className={`w-14 h-14 rounded-full flex items-center justify-center text-xs font-medium ${ui.center}`}
          >
            {safePercent}%
          </div>
        </div>
      </div>

      <div className={`mt-4 text-3xl font-semibold ${ui.text}`}>{value}</div>
    </div>
  );
}

export default function Dashboard() {
  const location = useLocation();
  const navigate = useNavigate();
  const enableDocs = import.meta.env.VITE_ENABLE_DOCS === "1";

  const [showWelcome, setShowWelcome] = useState(false);
  const [welcomeEmail, setWelcomeEmail] = useState<string | null>(null);

  const [cards, setCards] = useState<CompanyHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState<"all" | "green" | "yellow" | "red" | "neutral">("all");

  useEffect(() => {
    const st = location.state as any;
    if (st?.welcome) {
      setShowWelcome(true);
      setWelcomeEmail(st?.userEmail ?? null);
      navigate(".", { replace: true, state: {} });
    }
  }, [location.state, navigate]);

  useEffect(() => {
    let active = true;

    const loadDashboard = async () => {
      setLoading(true);
      setErr(null);

      try {
        const { data: companies } = await api.get("/api/v1/companies");

        const normalizedCompanies: Company[] = Array.isArray(companies) ? companies : [];

        const summaries = await Promise.all(
          normalizedCompanies.map(async (company) => {
            try {
              const { data } = await api.get(`/api/v1/companies/${company.id}/requirements`);
              const items = Array.isArray(data?.items) ? data.items : [];
              return summarizeCompany(company, items);
            } catch {
              return summarizeCompany(company, []);
            }
          })
        );

        if (!active) return;
        setCards(summaries);
      } catch (e: any) {
        if (!active) return;
        setErr(e?.response?.data?.detail ?? "No se pudo cargar el dashboard.");
      } finally {
        if (active) setLoading(false);
      }
    };

    loadDashboard();

    return () => {
      active = false;
    };
  }, []);

  const closeWelcome = () => setShowWelcome(false);

  const global = useMemo(() => {
    const totalCompanies = cards.length;
    const green = cards.filter((c) => c.level === "green").length;
    const yellow = cards.filter((c) => c.level === "yellow").length;
    const red = cards.filter((c) => c.level === "red").length;
    const avgCompliance =
      totalCompanies > 0
        ? Math.round(cards.reduce((acc, c) => acc + c.compliancePct, 0) / totalCompanies)
        : 0;

    const urgent = cards
      .flatMap((c) =>
        c.urgent.map((u) => ({
          companyId: c.id,
          companyName: c.name,
          activity: c.activity,
          ...u,
        }))
      )
      .sort((a, b) => {
        const weightA = a.level === "red" ? 0 : 1;
        const weightB = b.level === "red" ? 0 : 1;
        if (weightA !== weightB) return weightA - weightB;
        return new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime();
      })
      .slice(0, 10);

    return { totalCompanies, green, yellow, red, avgCompliance, urgent };
  }, [cards]);

  const filteredCards = useMemo(() => {
    const term = search.trim().toLowerCase();

    return cards.filter((card) => {
      const matchesSearch =
        term === "" ||
        card.name.toLowerCase().includes(term) ||
        card.activity.toLowerCase().includes(term);

      const matchesLevel =
        levelFilter === "all" || card.level === levelFilter;

      return matchesSearch && matchesLevel;
    });
  }, [cards, search, levelFilter]);

  return (
    <>
      <div className="space-y-4">
        <div className="grid lg:grid-cols-4 gap-4">
          <GaugeCard
            title="Empresas"
            value={global.totalCompanies}
            subtitle="Registradas en el sistema"
            percent={global.totalCompanies > 0 ? 100 : 0}
            tone="slate"
          />

          <GaugeCard
            title="Cumplimiento base"
            value={`${global.avgCompliance}%`}
            subtitle="Promedio preliminar por empresa"
            percent={global.avgCompliance}
            tone={
              global.avgCompliance >= 80
                ? "emerald"
                : global.avgCompliance >= 50
                ? "amber"
                : "red"
            }
          />

          <GaugeCard
            title="Semáforo general"
            value={`${global.green}/${global.totalCompanies}`}
            subtitle="Empresas en estado verde"
            percent={
              global.totalCompanies > 0
                ? Math.round((global.green / global.totalCompanies) * 100)
                : 0
            }
            tone={
              global.red > 0
                ? "red"
                : global.yellow > 0
                ? "amber"
                : "emerald"
            }
          />

          <GaugeCard
            title="Alertas críticas"
            value={global.urgent.length}
            subtitle="Vencidos y próximos 30 días"
            percent={
              global.totalCompanies > 0
                ? Math.min(100, Math.round((global.urgent.length / global.totalCompanies) * 100))
                : 0
            }
            tone={global.urgent.length > 0 ? "red" : "emerald"}
          />
        </div>

        <div className="card">
          <div className="mb-3 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-slate-900 dark:text-white">Estado por empresa</h2>
              <p className="muted text-sm">
                Revisa el estado general de cumplimiento y usa los filtros para detectar prioridades.
              </p>
            </div>

            <div className="flex gap-2 flex-wrap">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar empresa o actividad"
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-300 dark:border-white/10 dark:bg-slate-800 dark:text-white dark:focus:ring-white/10"
              />

              <select
                value={levelFilter}
                onChange={(e) =>
                  setLevelFilter(e.target.value as "all" | "green" | "yellow" | "red" | "neutral")
                }
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-300 dark:border-white/10 dark:bg-slate-800 dark:text-white dark:focus:ring-white/10"
              >
                <option value="all">Todos</option>
                <option value="green">Vigente</option>
                <option value="yellow">Próximo</option>
                <option value="red">Vencido</option>
                <option value="neutral">Sin datos</option>
              </select>
            </div>
          </div>

          {loading && <p className="muted">Cargando estado de cumplimiento…</p>}

          {!loading && err && (
            <div className="status-banner status-banner-danger text-sm">
              {err}
            </div>
          )}

          {!loading && !err && filteredCards.length === 0 && (
            <div className="empty-state">
              <div className="text-base font-medium text-slate-900 dark:text-white">
                No hay empresas que coincidan con los filtros aplicados.
              </div>
              <div className="muted mt-2">
                Ajusta el texto de búsqueda o cambia el filtro de estado para ampliar los resultados.
              </div>
            </div>
          )}

          {!loading && !err && filteredCards.length > 0 && (
            <div className="grid lg:grid-cols-2 gap-4">
              {filteredCards.map((card) => {
                const styles = levelStyles(card.level);

                return (
                  <div
                    key={card.id}
                    className={`rounded-2xl p-4 shadow-sm ${styles.card}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                          {card.name}
                        </h3>
                        <p className="muted mt-1 text-sm">{card.activity}</p>
                      </div>

                      <span
                        className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${styles.chip}`}
                      >
                        {styles.label}
                      </span>
                    </div>

                    <div className="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                      <div>
                        <p className="text-slate-500 dark:text-slate-400">Cumplidos</p>
                        <p className="font-semibold text-slate-900 dark:text-white">{card.compliant}</p>
                      </div>
                      <div>
                        <p className="text-slate-500 dark:text-slate-400">Pendientes</p>
                        <p className="font-semibold text-slate-900 dark:text-white">{card.pending}</p>
                      </div>
                      <div>
                        <p className="text-slate-500 dark:text-slate-400">Próximos</p>
                        <p className="font-semibold text-slate-900 dark:text-white">{card.dueSoon}</p>
                      </div>
                      <div>
                        <p className="text-slate-500 dark:text-slate-400">Vencidos</p>
                        <p className="font-semibold text-slate-900 dark:text-white">{card.expired}</p>
                      </div>
                    </div>

                    <div className="mt-4">
                      <p className="muted mb-1 text-sm">
                        Cumplimiento base: {card.compliancePct}%
                      </p>
                      <div className={`h-3 w-full overflow-hidden rounded-full ${styles.track}`}>
                        <div
                          className={`h-3 rounded-full ${styles.bar}`}
                          style={{ width: `${card.compliancePct}%` }}
                        />
                      </div>
                    </div>

                    <div className="mt-4 flex gap-2 flex-wrap">
                      <Link
                        to={`/companies/${card.id}`}
                        className="btn-secondary rounded-full"
                      >
                        Ver empresa
                      </Link>

                      {enableDocs && (
                        <Link
                          to={`/companies/${card.id}/documents`}
                          className="btn-primary rounded-full"
                        >
                          Ver documentos
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="card">
          <h2>Alertas priorizadas</h2>

          {loading && <p className="muted mt-2">Construyendo alertas…</p>}

          {!loading && !err && global.urgent.length === 0 && (
            <p className="muted mt-2">No hay vencimientos críticos para mostrar por ahora.</p>
          )}

          {!loading && !err && global.urgent.length > 0 && (
            <div className="mt-3 space-y-3">
              {global.urgent.map((alert, idx) => (
                <div
                  key={`${alert.companyId}-${alert.title}-${idx}`}
                  className={`rounded-xl px-3 py-3 ${
                    alert.level === "red"
                      ? "border border-red-200 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/10"
                      : "border border-amber-200 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-white">{alert.title}</p>
                      <p className="muted mt-1 text-sm">
                        {alert.companyName} · {alert.activity}
                      </p>

                      <div className="mt-3 flex gap-2 flex-wrap">
                        <Link
                          to={`/companies/${alert.companyId}`}
                          className="btn-secondary rounded-full"
                        >
                          Abrir empresa
                        </Link>

                        {enableDocs && (
                          <Link
                            to={`/companies/${alert.companyId}/documents`}
                            className="btn-primary rounded-full"
                          >
                            Ir a documentos
                          </Link>
                        )}
                      </div>
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
                      <p className="muted mt-2 text-sm">{formatDate(alert.dueDate)}</p>
                    </div>
                  </div>
                </div>                   
              ))}
            </div>
          )}
        </div>
      </div>

      <WelcomeOverlay open={showWelcome} onClose={closeWelcome} userEmail={welcomeEmail} />
    </>
  );
}