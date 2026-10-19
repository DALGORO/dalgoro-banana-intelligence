import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, ChevronRight, Layers3, MapPinned, Satellite, Search, ShieldCheck } from "lucide-react";
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
        <a href="#dbi-portal-farms" className="dbi-portal-hero-cta mt-6 inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold">
          Explorar mis fincas <ChevronRight size={18} aria-hidden="true" />
        </a>
      </header>

      <section className="dbi-portal-first-steps" aria-label="Cómo consultar el mapa de tu lote">
        <h2 className="text-base font-semibold">Tu mapa en tres pasos</h2>
        <ol className="dbi-portal-steps mt-3">
          <li><span aria-hidden="true">1</span><strong>Busca tu finca</strong></li>
          <li><span aria-hidden="true">2</span><strong>Abre el mapa de un lote</strong></li>
          <li><span aria-hidden="true">3</span><strong>Elige un vuelo y consulta sus capas</strong></li>
        </ol>
        <p className="muted mt-3 text-sm">
          Solo verás mapas y resultados publicados para tu lote. Si aún no hay cartografía
          autorizada, el visor te lo indicará.
        </p>
      </section>

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

      <section id="dbi-portal-farms" className="space-y-4" aria-label="Fincas y lotes autorizados">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h2 className="text-xl font-semibold">Mis fincas</h2>
            <p className="mt-1 text-sm text-slate-500">Elige un lote para abrir su mapa.</p>
          </div>
          <div className="dbi-portal-search-panel flex w-full flex-col gap-2 sm:w-auto">
            <label htmlFor="dbi-portal-search" className="text-sm font-medium">Buscar finca o lote</label>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="dbi-portal-search-field relative w-full sm:w-72">
                <Search className="dbi-portal-search-icon" size={18} aria-hidden="true" />
                <input
                  id="dbi-portal-search"
                  type="search"
                  aria-controls="dbi-portal-farms"
                  className="dbi-portal-search w-full rounded-xl border border-slate-300 bg-white py-3 pl-11 pr-4 text-sm dark:border-slate-600 dark:bg-slate-900"
                  placeholder="Nombre o código de finca o lote"
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                />
              </div>
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
          </div>
        </div>
        {!loading && !error && (
          <p className="dbi-portal-results text-sm" role="status" aria-live="polite">
            {search.trim() ? "Coincidencias: " : "Con acceso: "}
            {farms.length} {farms.length === 1 ? "finca" : "fincas"} y{" "}
            {totalPlots} {totalPlots === 1 ? "lote" : "lotes"}.
          </p>
        )}
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
                  {farm.code && <span className="dbi-portal-farm-code mt-2 inline-block text-xs font-semibold">Finca {farm.code}</span>}
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
                        {plot.code && <div className="dbi-portal-plot-code mt-1 text-xs">Lote {plot.code}</div>}
                        <div className="mt-1 text-xs text-slate-500">
                          {plot.area_hectares == null
                            ? "Superficie no registrada"
                            : `${plot.area_hectares.toLocaleString("es-EC", { maximumFractionDigits: 2 })} ha`}
                        </div>
                      </div>
                      <span className="dbi-portal-map-action inline-flex shrink-0 items-center gap-1 text-sm font-semibold">
                        Abrir mapa <ChevronRight size={17} aria-hidden="true" />
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
