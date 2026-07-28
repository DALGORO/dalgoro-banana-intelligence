import { Outlet, NavLink, useNavigate, useMatch, useLocation } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { api } from '@/app/api';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

type SubscriptionStatusLite = {
  plan?: string;
  status?: string;
  free_trial_until?: string | null;
};

type BillingBlockLite = {
  code?: string;
  detail?: string;
} | null;

type AuthMeLite = {
  roles?: string[];
};

function normalizePlan(value?: string | null) {
  return String(value ?? '').trim().toUpperCase().replace(/[-\s]+/g, '_');
}

function normalizeStatus(value?: string | null) {
  return String(value ?? '').trim().toUpperCase().replace(/[-\s]+/g, '_');
}

function isSubscriptionBlocked(sub: SubscriptionStatusLite | null) {
  if (!sub) return false;

  const plan = normalizePlan(sub.plan);
  const status = normalizeStatus(sub.status);

  if (status === 'PAST_DUE' || status === 'CANCELED') {
    return true;
  }

  if ((plan === 'FREE_TRIAL' || plan === 'TRIAL') && sub.free_trial_until) {
    const end = new Date(sub.free_trial_until);
    if (!Number.isNaN(end.getTime()) && end.getTime() < Date.now()) {
      return true;
    }
  }

  return false;
}

function formatPlanLabel(plan?: string | null) {
  const normalized = normalizePlan(plan);

  switch (normalized) {
    case 'FREE_TRIAL':
    case 'TRIAL':
      return 'Prueba';
    case 'BASIC':
      return 'Plan Base';
    case 'PRO':
      return 'Plan Pro';
    case 'ENTERPRISE':
      return 'Enterprise';
    default:
      return normalized ? normalized.replace(/_/g, ' ') : 'Sin plan';
  }
}

function isAdminRole(roles?: string[] | null) {
  return Array.isArray(roles) && roles.includes('ADMIN');
}

function healthBadgeClass(health: 'online' | 'offline' | 'checking') {
  if (health === 'online') {
    return 'chip bg-emerald-500/15 text-emerald-700 border-emerald-500/20 dark:text-emerald-300';
  }

  if (health === 'offline') {
    return 'chip bg-rose-500/15 text-rose-700 border-rose-500/20 dark:text-rose-300';
  }

  return 'chip bg-slate-500/10 text-slate-700 border-slate-400/20 dark:text-slate-200';
}

function healthLabel(health: 'online' | 'offline' | 'checking') {
  if (health === 'online') return 'Operativa';
  if (health === 'offline') return 'Sin conexión';
  return 'Verificando';
}

function getPageMeta(pathname: string) {
  if (pathname === '/') {
    return {
      title: 'Panel general',
      subtitle: 'Revisa el estado global de cumplimiento y detecta qué empresa requiere atención primero.',
    };
  }

  if (pathname.startsWith('/companies/') && pathname.includes('/documents')) {
    return {
      title: 'Documentos',
      subtitle: 'Consulta documentos generados y revisa qué acciones están disponibles según el estado de la cuenta.',
    };
  }

  if (pathname.startsWith('/companies/') && pathname.includes('/investigacion-incidentes')) {
    return {
      title: 'Investigación y consultas SST',
      subtitle: 'Resuelve dudas normativas, de implementación y de actuación ante incidentes, sin exponer detalles técnicos del sistema.',
    };
  }

  if (pathname.startsWith('/companies/') && pathname.includes('/iperc')) {
    return {
      title: 'IPERC',
      subtitle: 'Evalúa peligros, riesgos y controles con una lectura más clara del contexto de la empresa.',
    };
  }

  if (pathname.startsWith('/companies/')) {
    return {
      title: 'Detalle de empresa',
      subtitle: 'Administra información operativa, cumplimiento y módulos asociados a la empresa seleccionada.',
    };
  }

  if (pathname.startsWith('/companies')) {
    return {
      title: 'Empresas',
      subtitle: 'Registra, revisa y organiza las empresas dentro de tu cupo disponible.',
    };
  }

  if (pathname.startsWith('/pay')) {
    return {
      title: 'Activación y pago',
      subtitle: 'Recupera el acceso completo y vuelve a la última pantalla bloqueada.',
    };
  }

  if (pathname.startsWith('/admin')) {
    return {
      title: 'Administración de usuarios',
      subtitle: 'Controla usuarios, accesos, empresas por usuario y acciones administrativas del sistema.',
    };
  }

  return {
    title: 'SST Compliance',
    subtitle: 'Gestiona cumplimiento, empresas y documentación desde una sola plataforma.',
  };
}

const NavItem = ({ to, label }: { to: string; label: string }) => (
  <NavLink
    to={to}
    end={to === '/'}
    className={({ isActive }) => (isActive ? 'nav-item-active' : 'nav-item')}
  >
    {label}
  </NavLink>
);

export default function AppShell() {
  const nav = useNavigate();
  const location = useLocation();
  const matchCompanyBase = useMatch('/companies/:id');
  const matchCompanyNested = useMatch('/companies/:id/*');
  const companyId = matchCompanyNested?.params?.id ?? matchCompanyBase?.params?.id;
  const enableDocs = import.meta.env.VITE_ENABLE_DOCS === '1';

  const [health, setHealth] = useState<'online' | 'offline' | 'checking'>('checking');
  const [subStatus, setSubStatus] = useState<SubscriptionStatusLite | null>(null);
  const [billingBlock, setBillingBlock] = useState<BillingBlockLite>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isDark, setIsDark] = useState<boolean>(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark') return true;
    if (saved === 'light') return false;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  });

  useEffect(() => {
    const root = document.documentElement;

    if (isDark) {
      root.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      root.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [isDark]);

  useEffect(() => {
    api.get('/api/v1/health')
      .then(() => setHealth('online'))
      .catch(() => setHealth('offline'));
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('billing_block');
      setBillingBlock(raw ? JSON.parse(raw) : null);
    } catch {
      setBillingBlock(null);
    }

    api.get('/api/v1/subscriptions/status')
      .then((r) => setSubStatus(r.data))
      .catch(() => setSubStatus(null));
  }, []);

  useEffect(() => {
    let active = true;

    api.get('/api/v1/auth/me')
      .then((r) => {
        if (!active) return;
        const data = r.data as AuthMeLite;
        setIsAdmin(isAdminRole(data?.roles));
      })
      .catch(() => {
        if (!active) return;
        setIsAdmin(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const subscriptionBlocked =
    isSubscriptionBlocked(subStatus) ||
    billingBlock?.code === 'TRIAL_EXPIRED' ||
    billingBlock?.code === 'SUBSCRIPTION_INACTIVE';

  const showBillingBanner = subscriptionBlocked && location.pathname !== '/pay';

  const pageMeta = useMemo(() => getPageMeta(location.pathname), [location.pathname]);
  const planLabel = useMemo(() => formatPlanLabel(subStatus?.plan), [subStatus?.plan]);
  const statusLabel = subscriptionBlocked ? 'Restringido' : 'Activo';
  const billingMessage =
    billingBlock?.detail ?? 'Para recuperar las acciones bloqueadas, renueva tu suscripción.';

  const goToPay = () => {
    const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;

    try {
      sessionStorage.setItem('post_billing_redirect', currentPath || '/');
    } catch {
      // No hacer nada si falla sessionStorage.
    }

    nav('/pay');
  };

  return (
    <div className="min-h-screen grid md:grid-cols-[280px_1fr]">
      <aside className="app-sidebar border-r p-5">
        <div className="flex items-center gap-3 rounded-2xl border border-black/5 bg-white/40 px-4 py-4 dark:border-white/10 dark:bg-white/5">
          <div className="rounded-xl bg-[#192B2F] p-2 shadow-sm">
            <img src="/logo-white.png" alt="DALGORO" className="h-11 w-auto" />
          </div>

          <div>
            <div className="brand text-sm font-semibold text-slate-900 dark:text-white">DALGORO</div>
            <div className="text-xs text-slate-600 dark:text-white/70">
              Plataforma de cumplimiento SST guiada para operar con mayor claridad.
            </div>
          </div>
        </div>

        <nav className="mt-6 flex flex-col gap-1">
          <NavItem to="/" label="Dashboard" />
          <NavItem to="/companies" label="Empresas" />

          {isAdmin && (
            <NavItem to="/admin" label="Administración de usuarios" />
          )}

          {enableDocs && companyId && (
            <NavItem to={`/companies/${companyId}/documents`} label="Documentos" />
          )}

          {companyId && (
            <>
              <div className="mt-5 mb-1 px-3 text-[11px] uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                Empresa actual
              </div>

              <NavItem
                to={`/companies/${companyId}/investigacion-incidentes`}
                label="Investigación y consultas SST"
              />

              <NavItem to={`/companies/${companyId}/iperc`} label="IPERC" />
            </>
          )}
        </nav>

        <div className="sidebar-panel mt-8 space-y-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
              Estado del sistema
            </div>
            <div className="mt-1 text-sm text-slate-700 dark:text-white/80">
              Consulta rápida del acceso y del estado operativo antes de trabajar en los módulos.
            </div>
          </div>

          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-600 dark:text-white/70">API</span>
              <span className={healthBadgeClass(health)}>{healthLabel(health)}</span>
            </div>

            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-600 dark:text-white/70">Plan</span>
              <span className="chip">{planLabel}</span>
            </div>

            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-600 dark:text-white/70">Acceso</span>
              <span
                className={
                  subscriptionBlocked
                    ? 'chip bg-amber-500/15 text-amber-700 border-amber-500/20 dark:text-amber-200'
                    : 'chip bg-emerald-500/15 text-emerald-700 border-emerald-500/20 dark:text-emerald-200'
                }
              >
                {statusLabel}
              </span>
            </div>
          </div>
        </div>
      </aside>

      <main className="p-6 md:p-8">
        <header className="topbar mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="page-title-block">
            <div className="page-kicker">SST Compliance</div>
            <h1 className="text-2xl font-semibold">{pageMeta.title}</h1>
            <p className="page-subtitle max-w-3xl">{pageMeta.subtitle}</p>
          </div>

          <div className="flex items-center gap-2 self-start">
            <button onClick={() => setIsDark((d) => !d)} className="btn-secondary">
              {isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
            </button>

            <button
              className="btn-logout"
              onClick={() => {
                localStorage.removeItem('token');
                nav('/login');
              }}
            >
              Salir
            </button>
          </div>
        </header>

        {showBillingBanner && (
          <div className="status-banner status-banner-warning mb-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="font-medium">Suscripción vencida o inactiva</div>
                <div className="mt-1 text-sm opacity-90">
                  Puedes seguir revisando información visible, pero las acciones operativas permanecerán bloqueadas hasta renovar.
                </div>
                <div className="mt-1 text-sm opacity-80">{billingMessage}</div>
              </div>

              <button className="btn-primary" onClick={goToPay}>
                Renovar suscripción
              </button>
            </div>
          </div>
        )}

        <div className="grid gap-6">
          <Outlet />
        </div>

        <ToastContainer
          position="top-right"
          theme={isDark ? 'dark' : 'light'}
          newestOnTop
          closeOnClick
          pauseOnFocusLoss={false}
          draggable={false}
        />
      </main>
    </div>
  );
}