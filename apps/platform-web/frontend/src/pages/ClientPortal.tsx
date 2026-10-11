import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, ChevronRight, Layers3, MapPinned, Satellite, ShieldCheck } from "lucide-react";
import { api } from "@/app/api";

type Plot = { id: string; code: string; name: string; area_hectares: number | null };
type Farm = { id: string; organization_ref: string; code: string; name: string; plots: Plot[] };
type Account = { tenant_ref: string; farms: Farm[] };

function mapLink(tenant: string, farm: Farm, plot: Plot) {
  return `/dbi/organizations/${encodeURIComponent(farm.organization_ref)}/farms/${encodeURIComponent(farm.id)}/plots/${encodeURIComponent(plot.id)}/mapa?tenant=${encodeURIComponent(tenant)}`;
}

export default function ClientPortal() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let active = true;
    api.get<Account[]>("/api/v1/dbi/portal/accounts")
      .then(({ data }) => { if (active) setAccounts(data); })
      .catch((err) => { if (active) setError(
        err?.response?.status === 503
          ? "El catálogo agrícola no está disponible en este momento."
          : err?.response?.status === 401
            ? "Tu sesión expiró. Vuelve a iniciar sesión."
            : "No se pudieron consultar tus fincas. Intenta de nuevo."
      ); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const farms = useMemo(() => accounts.flatMap((account) =>
    account.farms.map((farm) => ({ account: account.tenant_ref, farm }))
  ).filter(({ farm }) =>
    `${farm.name} ${farm.code} ${farm.plots.map(p => p.name).join(" ")}`
      .toLocaleLowerCase("es").includes(search.trim().toLocaleLowerCase("es"))
  ), [accounts, search]);

  const totalPlots = accounts.reduce((total, account) =>
    total + account.farms.reduce((sum, farm) => sum + farm.plots.length, 0), 0);

  return (
    <main className="space-y-7 pb-10">
      <header className="rounded-3xl border border-emerald-800/10 bg-gradient-to-r from-[#163d34] via-[#205447] to-[#376c51] px-6 py-8 text-white shadow-sm sm:px-9">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-medium">
          <ShieldCheck size={15} /> Acceso privado a tus fincas
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Tu campo, en un solo lugar</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-white/85 sm:text-base">
          Explora los levantamientos de tus lotes, cambia de fecha y revisa los mapas agrícolas disponibles.
        </p>
      </header>

      <section aria-label="Resumen de fincas" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900">
          <MapPinned className="mb-3 text-emerald-700 dark:text-emerald-300" />
          <div className="text-3xl font-semibold">{loading ? "—" : farms.length}</div>
          <div className="mt-1 text-sm text-slate-500">Fincas visibles</div>
        </div>
        <div className="rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900">
          <Layers3 className="mb-3 text-emerald-700 dark:text-emerald-300" />
          <div className="text-3xl font-semibold">{loading ? "—" : totalPlots}</div>
          <div className="mt-1 text-sm text-slate-500">Lotes con acceso</div>
        </div>
        <div className="col-span-2 rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900 sm:col-span-1">
          <Satellite className="mb-3 text-emerald-700 dark:text-emerald-300" />
          <div className="font-semibold">Visor histórico</div>
          <div className="mt-1 text-sm text-slate-500">Solo capas con evidencia real</div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h2 className="text-xl font-semibold">Mis fincas</h2>
            <p className="mt-1 text-sm text-slate-500">Elige un lote para abrir su mapa.</p>
          </div>
          <input
            aria-label="Buscar finca o lote"
            className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm dark:border-slate-600 dark:bg-slate-900 sm:w-64"
            placeholder="Buscar finca o lote…"
            value={search}
            onChange={event => setSearch(event.target.value)}
          />
        </div>
        {loading && <div role="status" className="rounded-2xl border p-6">Cargando tus fincas…</div>}
        {error && <div role="alert" className="rounded-2xl border border-rose-300 p-6 text-rose-700">{error}</div>}
        {!loading && !error && farms.length === 0 && (
          <div className="rounded-2xl border bg-white p-8 text-center dark:bg-slate-900">
            <Building2 className="mx-auto mb-3 text-slate-400" size={30} />
            <h3 className="font-semibold">{search ? "No encontramos coincidencias" : "Aún no tienes fincas asignadas"}</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
              {search
                ? "Prueba otro nombre de finca o lote."
                : "Un administrador debe vincular tu usuario con una finca y sus lotes. No se muestran datos de otras cuentas."}
            </p>
          </div>
        )}
        {!loading && !error && (
          <div className="grid gap-4 lg:grid-cols-2">
            {farms.map(({ account, farm }) => (
              <article key={`${account}:${farm.id}`} className="overflow-hidden rounded-2xl border bg-white shadow-sm dark:bg-slate-900">
                <div className="border-b bg-emerald-50/60 px-5 py-4 dark:bg-emerald-950/20">
                  <div className="flex items-center gap-2 text-emerald-800 dark:text-emerald-200">
                    <MapPinned size={18} />
                    <h3 className="text-lg font-semibold">{farm.name}</h3>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    {farm.plots.length} {farm.plots.length === 1 ? "lote autorizado" : "lotes autorizados"}
                  </p>
                </div>
                <div className="divide-y">
                  {farm.plots.length === 0 && (
                    <p className="px-5 py-5 text-sm text-slate-500">
                      Tienes acceso a la finca, pero todavía no a ningún lote.
                    </p>
                  )}
                  {farm.plots.map(plot => (
                    <Link key={plot.id} to={mapLink(account, farm, plot)}
                      className="flex items-center justify-between gap-3 px-5 py-4 transition hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-emerald-500 dark:hover:bg-white/5"
                      aria-label={`Abrir visor de ${plot.name} en ${farm.name}`}>
                      <div>
                        <div className="font-medium">{plot.name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {plot.area_hectares == null
                            ? "Superficie no registrada"
                            : `${plot.area_hectares.toLocaleString("es-EC", { maximumFractionDigits: 2 })} ha`}
                        </div>
                      </div>
                      <span className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
                        Ver mapa <ChevronRight size={17} />
                      </span>
                    </Link>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
