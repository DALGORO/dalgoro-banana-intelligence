import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, ChevronRight, Layers3, MapPinned, Satellite, ShieldCheck } from "lucide-react";
import { api } from "@/app/api";
import {
  filterClientPortalFarms,
  type ClientPortalAccount as Account,
  type ClientPortalFarm as Farm,
  type ClientPortalPlot as Plot,
} from "@/features/clientPortalSearch";

function mapLink(tenant: string, farm: Farm, plot: Plot) {
  return `/dbi/organizations/${encodeURIComponent(farm.organization_ref)}/farms/${encodeURIComponent(farm.id)}/plots/${encodeURIComponent(plot.id)}/mapa?tenant=${encodeURIComponent(tenant)}`;
}

export default function ClientPortal() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
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
  }, [reloadKey]);

  const farms = useMemo(
    () => filterClientPortalFarms(accounts, search),
    [accounts, search],
  );

  // Contadores y tarjetas responden al MISMO filtro READ autorizado.
  const totalPlots = farms.reduce((total, { visiblePlots }) => total + visiblePlots.length, 0);
  const retry = () => setReloadKey(key => key + 1);

  return (
    <main className="dbi-portal-home space-y-7 pb-10">
      <header className="dbi-portal-hero rounded-3xl px-6 py-8 text-white shadow-sm sm:px-9">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-medium">
          <ShieldCheck size={15} /> Acceso privado a tus fincas
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Tu campo, en un solo lugar</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-white/85 sm:text-base">
          Selecciona una finca y abre el mapa de tu lote para consultar sus campañas, capas y evidencias disponibles.
        </p>
      </header>

      <section aria-label="Resumen de fincas" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900">
          <MapPinned className="mb-3 text-[#9f643c] dark:text-[#e6b18a]" />
          <div className="text-3xl font-semibold">{loading || error ? "—" : farms.length}</div>
          <div className="mt-1 text-sm text-slate-500">Fincas en esta búsqueda</div>
        </div>
        <div className="rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900">
          <Layers3 className="mb-3 text-[#9f643c] dark:text-[#e6b18a]" />
          <div className="text-3xl font-semibold">{loading || error ? "—" : totalPlots}</div>
          <div className="mt-1 text-sm text-slate-500">Lotes en esta búsqueda</div>
        </div>
        <div className="col-span-2 rounded-2xl border bg-white p-5 shadow-sm dark:bg-slate-900 sm:col-span-1">
          <Satellite className="mb-3 text-[#9f643c] dark:text-[#e6b18a]" />
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
            className="dbi-portal-search w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm dark:border-slate-600 dark:bg-slate-900 sm:w-64"
            placeholder="Buscar finca o lote…"
            value={search}
            onChange={event => setSearch(event.target.value)}
          />
          {search.trim() && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="dbi-portal-retry rounded-xl px-4 py-3 text-sm font-semibold"
              aria-label="Limpiar búsqueda de finca o lote"
            >
              Limpiar búsqueda
            </button>
          )}
        </div>
        {loading && <div role="status" aria-live="polite" className="rounded-2xl border p-6">Cargando tus fincas…</div>}
        {error && (
          <div role="alert" className="dbi-portal-error rounded-2xl border p-6">
            <p>{error}</p>
            <button type="button" onClick={retry} className="dbi-portal-retry mt-4 rounded-xl px-4 py-3 text-sm font-semibold">
              Reintentar consulta
            </button>
          </div>
        )}
        {!loading && !error && farms.length === 0 && (
          <div className="rounded-2xl border bg-white p-8 text-center dark:bg-slate-900">
            <Building2 className="mx-auto mb-3 text-slate-400" size={30} />
            <h3 className="font-semibold">{search.trim() ? "No encontramos coincidencias" : "Aún no tienes fincas asignadas"}</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
              {search.trim()
                ? "Prueba otro nombre o código de finca o lote, o limpia la búsqueda."
                : "Un administrador debe vincular tu usuario con una finca y sus lotes. No se muestran datos de otras cuentas."}
            </p>
          </div>
        )}
        {!loading && !error && (
          <div className="grid gap-4 lg:grid-cols-2">
            {farms.map(({ account, farm, visiblePlots }) => (
              <article key={`${account}:${farm.id}`} className="overflow-hidden rounded-2xl border bg-white shadow-sm dark:bg-slate-900">
                <div className="dbi-portal-farm-header border-b px-5 py-4">
                  <div className="flex items-center gap-2 text-[#17343a] dark:text-[#edf5f0]">
                    <MapPinned size={18} />
                    <h3 className="text-lg font-semibold">{farm.name}</h3>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    {visiblePlots.length} {visiblePlots.length === 1 ? "lote visible" : "lotes visibles"}
                  </p>
                </div>
                <div className="divide-y">
                  {visiblePlots.length === 0 && (
                    <p className="px-5 py-5 text-sm text-slate-500">
                      Tienes acceso a la finca, pero todavía no a ningún lote.
                    </p>
                  )}
                  {visiblePlots.map(plot => (
                    <Link key={plot.id} to={mapLink(account, farm, plot)}
                      className="dbi-portal-plot-link flex items-center justify-between gap-3 px-5 py-4 transition dark:hover:bg-white/5"
                      aria-label={`Abrir visor de ${plot.name} en ${farm.name}`}>
                      <div>
                        <div className="font-medium">{plot.name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {plot.area_hectares == null
                            ? "Superficie no registrada"
                            : `${plot.area_hectares.toLocaleString("es-EC", { maximumFractionDigits: 2 })} ha`}
                        </div>
                      </div>
                      <span className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-[#9f643c] dark:text-[#e6b18a]">
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
