import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api, generateIncidentProcedurePdf, getCompanyDocuments, getCompanyRequirements } from "../app/api";

type Doc = { id: number; title: string; kind: string; created_at: string; mime: string };
type ReqItem = {
  code: string;
  name: string;
  periodicity: string;
  legal: string;
  exists?: boolean;
  can_generate?: boolean;            // NUEVO
  next_due_date?: string | null;     // NUEVO
  disabled_reason?: string | null;   // NUEVO
  priority_order?: number;
  priority_message?: string;
};
type ReqPayload = { clasificacion: string; riesgo: string; actividad: string; items: ReqItem[] };

type SubscriptionStatusLite = {
  plan?: string;
  status?: string;
  free_trial_until?: string | null;
};

function normalizePlan(value?: string | null) {
  return String(value ?? "").trim().toUpperCase().replace(/[-\s]+/g, "_");
}

function normalizeStatus(value?: string | null) {
  return String(value ?? "").trim().toUpperCase().replace(/[-\s]+/g, "_");
}

function isSubscriptionBlocked(sub: SubscriptionStatusLite | null) {
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

function formatDate(value?: string | null) {
  const d = dateOnly(value);
  if (!d) return "—";
  return d.toLocaleDateString("es-EC");
}

function docTypeUi(mime?: string) {
  const m = String(mime ?? "").toLowerCase();

  if (m.includes("pdf")) {
    return {
      label: "PDF",
      badge: "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200",
    };
  }

  if (m.includes("wordprocessingml.document")) {
    return {
      label: "DOCX",
      badge: "border border-sky-200 bg-sky-100 text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/20 dark:text-sky-200",
    };
  }

  if (m.includes("spreadsheetml.sheet")) {
    return {
      label: "XLSX",
      badge: "border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200",
    };
  }

  return {
    label: "ARCHIVO",
    badge: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
  };
}

function requirementUi(it: ReqItem) {
  const today = new Date();
  const todayOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const due = dateOnly(it.next_due_date);
  const disabledReason = String(it.disabled_reason ?? "").trim().toUpperCase();

  if (due) {
    const diff = daysBetween(todayOnly, due);

    if (diff < 0) {
      return {
        label: "Vencido",
        badge: "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200",
        text: `Venció el ${formatDate(it.next_due_date)}`,
        level: "red" as const,
      };
    }

    if (diff <= 30) {
      return {
        label: "Próximo",
        badge: "border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200",
        text: `Vence el ${formatDate(it.next_due_date)}`,
        level: "yellow" as const,
      };
    }
  }

  if (!(it.can_generate ?? !it.exists) || disabledReason.includes("CUMPLIDO")) {
    return {
      label: "Vigente",
      badge: "border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200",
      text:
        it.disabled_reason ??
        (it.next_due_date ? `Próxima: ${formatDate(it.next_due_date)}` : "Cumplido"),
      level: "green" as const,
    };
  }

  return {
    label: "Pendiente",
    badge: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
    text: "Aún no generado",
    level: "neutral" as const,
  };
}

export default function Documents() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [subStatus, setSubStatus] = useState<SubscriptionStatusLite | null>(null);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [generatingInvProcedure, setGeneratingInvProcedure] = useState(false);

  // ✅ ÚNICA declaración (tipada) del estado de requisitos
  const [req, setReq] = useState<ReqPayload | null>(null);
  const subscriptionBlocked = isSubscriptionBlocked(subStatus);

  const goToPay = () => {
    const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    try {
      sessionStorage.setItem("post_billing_redirect", currentPath || `/companies/${id}/documents`);
    } catch {}
    navigate("/pay");
  };
  const handleGenerateIncidentProcedurePdf = async () => {
    if (!id || generatingInvProcedure) return;

    try {
      setGeneratingInvProcedure(true);
      setErr(null);

      const response = await generateIncidentProcedurePdf(Number(id));
      const data = response.data ?? {};

      if (data?.id) {
        navigate(`/documents/${data.id}`, {
          state: {
            title: data?.title ?? "INV-AT-01 Procedimiento documentado",
            mime: "application/pdf",
          },
        });
        return;
      }

      const docsRes = await getCompanyDocuments(Number(id));
      setDocs(docsRes.data);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? "No se pudo generar el PDF del procedimiento.");
    } finally {
      setGeneratingInvProcedure(false);
    }
  };
  const deleteDoc = async (docId: number) => {
    if (!confirm("¿Eliminar el documento? Esta acción no se puede deshacer.")) return;

    try {
      await api.delete(`/documents/${docId}`);
      setDocs(prev => prev.filter(d => d.id !== docId));
      setErr(null);
    } catch (e: any) {
      const detail =
        e?.response?.data?.detail ??
        "No se pudo eliminar. Revisa permisos o el estado de tu suscripción.";
      setErr(detail);
      alert(detail);
    }
  };
  useEffect(() => {
    let mounted = true;

    (async () => {
      setLoadingDocs(true);

      try {
        const docsRes = await getCompanyDocuments(Number(id));
        if (mounted) {
          setDocs(docsRes.data);
          setErr(null);
        }
      } catch (e: any) {
        if (mounted) {
          setErr(e?.response?.data?.detail ?? "No se pudieron cargar los documentos.");
        }
      } finally {
        if (mounted) {
          setLoadingDocs(false);
        }
      }

      try {
        const reqRes = await getCompanyRequirements(Number(id));
        if (mounted) {
          setReq(reqRes.data);
        }
      } catch {
        if (mounted) {
          setReq(null);
        }
      }

      try {
        const { data: me } = await api.get("/auth/me");
        if (mounted) {
          setIsAdmin(Array.isArray(me?.roles) && me.roles.includes("ADMIN"));
        }
      } catch {
        if (mounted) {
          setIsAdmin(false);
        }
      }

      try {
        const { data } = await api.get("/subscriptions/status");
        if (mounted) {
          setSubStatus(data);
        }
      } catch {
        if (mounted) {
          try {
            const raw = sessionStorage.getItem("billing_block");
            if (raw) {
              const parsed = JSON.parse(raw);
              setSubStatus({
                plan: parsed?.plan,
                status: parsed?.status,
                free_trial_until: parsed?.free_trial_until ?? null,
              });
            } else {
              setSubStatus(null);
            }
          } catch {
            setSubStatus(null);
          }
        }
      }
    })();

    return () => {
      mounted = false;
    };
  }, [id]);
  
  // ⬇️ ORDENAR: prioridad asc (undefined al final), luego por código
  const orderedItems = [...(req?.items ?? [])].sort((a, b) => {
    const pa = Number.isFinite(a.priority_order) ? (a.priority_order as number) : Infinity;
    const pb = Number.isFinite(b.priority_order) ? (b.priority_order as number) : Infinity;
    if (pa !== pb) return pa - pb;
    return String(a.code).localeCompare(String(b.code));
  });

  const summary = useMemo(() => {
    let green = 0;
    let yellow = 0;
    let red = 0;
    let neutral = 0;

    for (const it of orderedItems) {
      const ui = requirementUi(it);
      if (ui.level === "green") green += 1;
      else if (ui.level === "yellow") yellow += 1;
      else if (ui.level === "red") red += 1;
      else neutral += 1;
    }

    return {
      totalDocs: docs.length,
      green,
      yellow,
      red,
      neutral,
    };
  }, [orderedItems, docs]);

  if (loadingDocs) {
    return (
      <div className="card">
        <p className="muted">{err ?? "Cargando documentos…"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">Módulo documental</span>
          <h1>Documentos</h1>
          <p className="page-subtitle">
            Revisa documentos generados y el estado de los requisitos aplicables a esta empresa.
          </p>
        </div>

        <Link to={`/companies/${id}`} className="btn-secondary">
          ← Volver
        </Link>
      </div>

      {err && (
        <div className="status-banner status-banner-danger text-sm">
          {err}
        </div>
      )}

      {subscriptionBlocked && (
        <div className="status-banner status-banner-warning text-sm">
          Puedes ver qué documentos existen en el sistema, pero para abrirlos, descargarlos o visualizarlos en PDF debes renovar tu suscripción.
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="metric-card">
          <p className="muted text-sm">Documentos existentes</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{summary.totalDocs}</p>
        </div>

        <div className="metric-card border border-emerald-200 bg-emerald-50/80 dark:border-emerald-500/20 dark:bg-emerald-500/10">
          <p className="text-sm text-emerald-700 dark:text-emerald-200">Vigentes</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{summary.green}</p>
        </div>

        <div className="metric-card border border-amber-200 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10">
          <p className="text-sm text-amber-700 dark:text-amber-200">Próximos</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{summary.yellow}</p>
        </div>

        <div className="metric-card border border-red-200 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/10">
          <p className="text-sm text-red-700 dark:text-red-200">Vencidos</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{summary.red}</p>
        </div>
      </div>

      <div className="surface p-0 overflow-hidden">
        <div className="section-head border-b border-slate-200 px-4 py-4 dark:border-white/10">
          <div>
            <h2 className="text-lg">Documentos existentes</h2>
            <p className="muted mt-1">Listado histórico de archivos ya generados para esta empresa.</p>
          </div>
        </div>

        <ul className="divide-y divide-slate-200 dark:divide-white/10">
          {docs.map((d) => {
            const typeUi = docTypeUi(d.mime);

            return (
              <li key={d.id} className="flex items-center justify-between gap-3 p-4 flex-wrap">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium text-slate-900 dark:text-white">{d.title}</div>
                    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${typeUi.badge}`}>
                      {typeUi.label}
                    </span>
                  </div>

                  <div className="muted mt-1 text-xs">
                    {new Date(d.created_at).toLocaleString("es-EC", { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </div>

                <div className="flex gap-2 flex-wrap">
                  <button
                    type="button"
                    onClick={() => {
                      if (subscriptionBlocked) {
                        goToPay();
                        return;
                      }

                      navigate(`/documents/${d.id}`, {
                        state: { title: d.title, mime: d.mime },
                      });
                    }}
                    className="btn-primary text-sm"
                    title={
                      subscriptionBlocked
                        ? "Tu cuenta está inactiva. Haz clic para renovar tu suscripción."
                        : "Abrir documento"
                    }
                  >
                    Abrir
                  </button>

                  {isAdmin && (
                    <button
                      onClick={() => deleteDoc(d.id)}
                      className="btn border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200 dark:hover:bg-red-500/20 text-sm"
                    >
                      Eliminar
                    </button>
                  )}
                </div>
              </li>
            );
          })}

          {docs.length === 0 && (
            <li className="p-4">
              <div className="empty-state">
                <div className="text-base font-medium text-slate-900 dark:text-white">No hay documentos aún.</div>
                <div className="muted mt-2">
                  El siguiente paso recomendado es revisar los requisitos pendientes y generar el primer documento aplicable.
                </div>
              </div>
            </li>
          )}
        </ul>
      </div>

      {req && (
        <div className="surface p-0 overflow-hidden">
          <div className="section-head border-b border-slate-200 px-4 py-4 dark:border-white/10 flex-wrap">
            <div>
              <h2 className="text-lg">Requisitos normativos</h2>
              <div className="muted mt-1 text-xs">
                {req.actividad} · {req.clasificacion} · Riesgo {req.riesgo}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600 dark:bg-white/5 dark:text-slate-300">
                <tr>
                  <th className="px-4 py-3 text-left">Código</th>
                  <th className="px-4 py-3 text-left">Requisito</th>
                  <th className="px-4 py-3 text-left">Periodicidad</th>
                  <th className="px-4 py-3 text-left">Base legal</th>
                  <th className="px-4 py-3 text-left">Motivo</th>
                  <th className="px-4 py-3 text-left">Estado</th>
                  <th className="px-4 py-3 text-left">Acciones</th>
                </tr>
              </thead>

              <tbody>
                {orderedItems.map((it) => {
                  return (
                    <tr key={it.code} className="border-t border-slate-200 align-top hover:bg-slate-50/70 dark:border-white/10 dark:hover:bg-white/[0.03]">
                      <td className="px-4 py-3 text-slate-900 dark:text-slate-200">
                        <span className="inline-flex items-center gap-2 flex-wrap">
                          {it.code}
                          {Number.isFinite(it.priority_order) && (
                            <span
                              title={it.priority_message || "Prioridad sugerida de implementación"}
                              className="inline-block rounded-full border border-amber-200 bg-amber-100 px-2 py-[2px] text-xs text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200"
                            >
                              Prioridad {it.priority_order}
                            </span>
                          )}
                        </span>
                      </td>

                      <td className="px-4 py-3 text-slate-900 dark:text-slate-100">{it.name}</td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{it.periodicity}</td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{it.legal}</td>

                      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-300">
                        {it.priority_message ? (
                          <span className="line-clamp-2" title={it.priority_message}>
                            {it.priority_message}
                          </span>
                        ) : (
                          <span className="text-slate-400 dark:text-slate-500">—</span>
                        )}
                      </td>

                      <td className="px-4 py-3">
                        {(() => {
                          const ui = requirementUi(it);

                          return (
                            <div className="space-y-1">
                              <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${ui.badge}`}>
                                {ui.label}
                              </span>
                              <div className="text-xs text-slate-500 dark:text-slate-400">{ui.text}</div>
                            </div>
                          );
                        })()}
                      </td>

                      <td className="px-4 py-3">
                        {String(it.code ?? "").toUpperCase() === "INV-AT-01" ? (
                          <div className="flex gap-2 flex-wrap">
                            <button
                              type="button"
                              className="btn-secondary text-sm"
                              onClick={() => navigate(`/companies/${id}/investigacion-incidentes`)}
                            >
                              Abrir módulo
                            </button>

                            <button
                              type="button"
                              className="btn-primary text-sm disabled:opacity-60"
                              disabled={generatingInvProcedure}
                              onClick={() => {
                                if (subscriptionBlocked) {
                                  goToPay();
                                  return;
                                }
                                handleGenerateIncidentProcedurePdf();
                              }}
                            >
                              {generatingInvProcedure ? "Generando PDF..." : "Generar PDF"}
                            </button>
                          </div>
                        ) : (it.can_generate ?? !it.exists) ? (
                          <button
                            type="button"
                            className="btn-primary text-sm"
                            onClick={() => {
                              navigate(`/companies/${id}/documents/new/${encodeURIComponent(it.code)}`);
                            }}
                          >
                            Generar
                          </button>
                        ) : (
                          <span className="text-xs text-slate-500 dark:text-slate-400">
                            {it.disabled_reason
                              ?? (it.next_due_date
                                ? `Cumplido. Próxima: ${new Date(it.next_due_date).toLocaleDateString("es-EC")}`
                                : "Cumplido")}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}

                {orderedItems.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-slate-500 dark:text-slate-400">
                      No hay requisitos para mostrar.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
