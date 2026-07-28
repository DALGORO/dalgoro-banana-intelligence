import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../app/api";

type BillingBlock = {
  detail?: string;
  code?: string;
  plan?: string;
  status?: string;
  free_trial_until?: string | null;
};

type SubscriptionStatus = {
  plan: string;
  status: string;
  free_trial_until?: string | null;
  current_period_end?: string | null;
  companies_quota: number;
  days_left?: number | null;
};

type CheckoutItem = "BASE_PLAN" | "EXTRA_COMPANY";

type CheckoutOut = {
  provider: string;
  checkout_url: string;
  session_id: string;
  expires_at: string;
};

function formatDateTime(value?: string | null) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString("es-EC", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function PaymentPage() {
  const navigate = useNavigate();

  const [flags, setFlags] = useState<any>(null);
  const [me, setMe] = useState<any>(null);
  const [subStatus, setSubStatus] = useState<SubscriptionStatus | null>(null);
  const [billingBlock, setBillingBlock] = useState<BillingBlock | null>(null);
  const [busyItem, setBusyItem] = useState<CheckoutItem | null>(null);
  const [checkoutMsg, setCheckoutMsg] = useState<string | null>(null);
  const [returnPath, setReturnPath] = useState("/");

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("billing_block");
      if (raw) {
        setBillingBlock(JSON.parse(raw));
      }
    } catch {
      setBillingBlock(null);
    }

    try {
      const savedPath = sessionStorage.getItem("post_billing_redirect");
      if (savedPath && savedPath !== "/pay") {
        setReturnPath(savedPath);
      }
    } catch {
      setReturnPath("/");
    }

    api.get("/api/v1/system/flags").then((r) => setFlags(r.data)).catch(() => setFlags(null));
    api.get("/api/v1/auth/me").then((r) => setMe(r.data)).catch(() => setMe(null));
    api.get("/api/v1/subscriptions/status").then((r) => setSubStatus(r.data)).catch(() => setSubStatus(null));
  }, []);

  const required = !!flags?.payment_required;
  const isPending = Array.isArray(me?.roles) && me.roles.includes("PENDING");

  const hasBasePlanActive =
    subStatus?.plan === "PROFESSIONAL_BASE" && subStatus?.status === "ACTIVE";

  const planLabel = useMemo(() => {
    if (!subStatus?.plan) return "Sin plan";
    if (subStatus.plan === "FREE_TRIAL") return "Trial gratuito";
    if (subStatus.plan === "PROFESSIONAL_BASE") return "Plan Base Profesional";
    return subStatus.plan;
  }, [subStatus]);

  const statusUi = useMemo(() => {
    switch (subStatus?.status) {
      case "ACTIVE":
        return {
          label: "Activo",
          className: "border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200",
        };
      case "PAST_DUE":
        return {
          label: "Pago pendiente",
          className: "border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200",
        };
      case "CANCELED":
        return {
          label: "Cancelado",
          className: "border border-red-200 bg-red-100 text-red-700 dark:border-red-500/20 dark:bg-red-500/20 dark:text-red-200",
        };
      default:
        return {
          label: subStatus?.status ?? "Sin estado",
          className: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-slate-700 dark:text-slate-300",
        };
    }
  }, [subStatus]);

  const message = useMemo(() => {
    if (billingBlock?.code === "TRIAL_EXPIRED") {
      return "Tu periodo de prueba terminó. Desde esta pantalla puedes activar el Plan Base para recuperar el acceso completo.";
    }

    if (billingBlock?.code === "SUBSCRIPTION_INACTIVE") {
      return "Tu suscripción no está activa. Regulariza el pago desde aquí para volver a usar los módulos bloqueados.";
    }

    if (billingBlock?.detail) return billingBlock.detail;

    if (required && isPending) {
      return "Tu cuenta quedó pendiente de activación. Ya puedes iniciar la sesión de checkout de prueba desde esta pantalla.";
    }

    return "Desde aquí podrás revisar tu estado de suscripción y activar los productos disponibles.";
  }, [billingBlock, required, isPending]);

  const startCheckout = async (item: CheckoutItem) => {
    if (item === "EXTRA_COMPANY" && !hasBasePlanActive) {
      setCheckoutMsg("Primero debes activar el Plan Base antes de comprar una empresa adicional.");
      return;
    }

    setBusyItem(item);
    setCheckoutMsg(null);

    try {
      const r = await api.post("/api/v1/subscriptions/checkout-session", { item });
      const data = r.data as CheckoutOut;

      const isStub =
        !data?.checkout_url ||
        data.checkout_url.includes("sandbox.example");

      if (isStub) {
        setCheckoutMsg(
          `Sesión de pago de prueba creada correctamente. Proveedor: ${data.provider}. Session ID: ${data.session_id}. Cuando conectes una pasarela real, este mismo botón te redirigirá automáticamente.`
        );
        return;
      }

      setCheckoutMsg(`Redirigiendo a ${data.provider}...`);
      window.location.assign(data.checkout_url);
    } catch (e: any) {
      setCheckoutMsg(
        e?.response?.data?.detail || "No se pudo iniciar la sesión de pago."
      );
    } finally {
      setBusyItem(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="card space-y-5">
        <div className="section-head flex-wrap">
          <div className="page-title-block">
            <span className="page-kicker">Facturación y acceso</span>
            <h1>Activación de suscripción</h1>
            <p className="page-subtitle">{message}</p>
          </div>

          <div className="flex gap-2 flex-wrap">
            <span className="chip">{planLabel}</span>
            <span className={`chip ${statusUi.className}`}>{statusUi.label}</span>
            {billingBlock?.code && (
              <span className="chip border border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-200">
                {billingBlock.code}
              </span>
            )}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div className="surface">
            <p className="muted text-sm">Usuario</p>
            <p className="font-medium mt-1 break-all">{me?.email ?? "—"}</p>
          </div>

          <div className="surface">
            <p className="muted text-sm">Ruta a recuperar</p>
            <p className="font-medium mt-1 break-all">{returnPath || "/"}</p>
          </div>

          <div className="surface">
            <p className="muted text-sm">Cupo de empresas</p>
            <p className="font-medium mt-1">
              {typeof subStatus?.companies_quota === "number" ? subStatus.companies_quota : "—"}
            </p>
          </div>

          <div className="surface">
            <p className="muted text-sm">Días restantes de trial</p>
            <p className="font-medium mt-1">
              {typeof subStatus?.days_left === "number" ? subStatus.days_left : "—"}
            </p>
          </div>

          <div className="surface">
            <p className="muted text-sm">Fin del trial</p>
            <p className="font-medium mt-1">{formatDateTime(subStatus?.free_trial_until)}</p>
          </div>

          <div className="surface">
            <p className="muted text-sm">Fin del periodo actual</p>
            <p className="font-medium mt-1">{formatDateTime(subStatus?.current_period_end)}</p>
          </div>
        </div>

        {billingBlock ? (
          <div className="status-banner status-banner-warning text-sm">
            <div className="font-medium">Acceso temporalmente bloqueado</div>
            <div className="mt-1">{message}</div>
            {billingBlock.free_trial_until ? (
              <div className="mt-1">Fin del trial registrado: {formatDateTime(billingBlock.free_trial_until)}</div>
            ) : null}
          </div>
        ) : (
          <div className="status-banner status-banner-info text-sm">
            Estado consultado correctamente. Puedes usar esta pantalla para revisar tu plan actual y preparar la activación.
          </div>
        )}

        {checkoutMsg && (
          <div className="status-banner status-banner-success text-sm">{checkoutMsg}</div>
        )}

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="surface">
            <div className="eyebrow mb-2">Producto principal</div>
            <h2 className="text-lg">Plan Base Profesional</h2>
            <p className="muted mt-2">
              Reactiva el acceso general a los módulos del sistema y recupera la operación normal cuando el trial terminó o la suscripción quedó inactiva.
            </p>
          </div>

          <div className="surface">
            <div className="eyebrow mb-2">Escalamiento</div>
            <h2 className="text-lg">Empresas adicionales</h2>
            <p className="muted mt-2">
              Esta compra se mantiene disponible solo cuando el Plan Base ya está activo, para evitar intentos de ampliación sin suscripción principal vigente.
            </p>
          </div>
        </div>

        {(subStatus || billingBlock || (required && isPending)) ? (
          <div className="space-y-4 pt-1">
            <div className="flex gap-2 flex-wrap">
              <button
                className="btn-primary"
                onClick={() => startCheckout("BASE_PLAN")}
                disabled={busyItem !== null}
              >
                {busyItem === "BASE_PLAN" ? "Procesando..." : "Activar Plan Base"}
              </button>

              <button
                className="btn-ghost"
                onClick={() => startCheckout("EXTRA_COMPANY")}
                disabled={busyItem !== null}
                title={hasBasePlanActive ? "Comprar empresa adicional" : "Activa primero el Plan Base"}
              >
                {busyItem === "EXTRA_COMPANY" ? "Procesando..." : "Comprar empresa adicional"}
              </button>
            </div>

            {!hasBasePlanActive && (
              <p className="muted text-sm">
                La compra de empresas adicionales se habilita cuando el Plan Base esté activo.
              </p>
            )}

            <div className="flex gap-2 flex-wrap">
              <button className="btn-ghost" onClick={() => navigate(returnPath || "/")}>
                Volver a la pantalla bloqueada
              </button>

              <button
                className="btn-ghost"
                onClick={() => {
                  sessionStorage.removeItem("billing_block");
                  navigate("/");
                }}
              >
                Ir al dashboard
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2 flex-wrap pt-1">
            <button className="btn-ghost" onClick={() => navigate(returnPath || "/")}>
              Volver
            </button>

            <button className="btn-ghost" onClick={() => navigate("/")}>
              Ir al dashboard
            </button>
          </div>
        )}
      </div>
    </div>
  );
}