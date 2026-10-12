/** Filtrado local de un catálogo previamente autorizado por servidor.
 *
 * No consulta otros tenants ni infiere campañas, permisos o indicadores.
 * Una coincidencia de finca muestra todos sus lotes autorizados;
 * una coincidencia sólo de lote muestra los lotes coincidentes.
 */
export type ClientPortalPlot = {
  id: string;
  code: string;
  name: string;
  area_hectares: number | null;
};
export type ClientPortalFarm = {
  id: string;
  organization_ref: string;
  code: string;
  name: string;
  plots: ClientPortalPlot[];
};
export type ClientPortalAccount = {
  tenant_ref: string;
  farms: ClientPortalFarm[];
};
export type VisibleClientPortalFarm = {
  account: string;
  farm: ClientPortalFarm;
  visiblePlots: ClientPortalPlot[];
};

function normalized(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es").replace(/\s+/g, " ").trim();
}

export function filterClientPortalFarms(
  accounts: readonly ClientPortalAccount[],
  search: string,
): VisibleClientPortalFarm[] {
  const query = normalized(search);
  return accounts.flatMap(account => account.farms.flatMap(farm => {
    const farmMatches = !query || normalized(`${farm.name} ${farm.code}`).includes(query);
    const visiblePlots = farmMatches
      ? farm.plots
      : farm.plots.filter(plot =>
          normalized(`${plot.name} ${plot.code}`).includes(query));
    return farmMatches || visiblePlots.length
      ? [{ account: account.tenant_ref, farm, visiblePlots }]
      : [];
  }));
}
