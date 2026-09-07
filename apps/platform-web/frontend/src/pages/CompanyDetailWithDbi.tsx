import { Link, useParams } from "react-router-dom";

export default function CompanyDetailWithDbi() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-5">
      <div className="surface space-y-4">
        <div className="page-title-block">
          <span className="page-kicker">DALGORO Banana Intelligence – sistema geoespacial</span>
          <h1>Empresa seleccionada</h1>
          <p className="page-subtitle">
            Prepara la finca y la ortofoto una sola vez; luego ejecuta el análisis completo de densidad de siembra con el mismo motor que ya utilizas.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          {id && (
            <>
              <Link className="btn-secondary" to={`/companies/${id}/agricultura`}>
                Preparar finca / ortofoto
              </Link>
              <Link className="btn-primary" to={`/companies/${id}/agricultura/densidad`}>
                Densidad de siembra
              </Link>
            </>
          )}
          <Link className="btn-ghost" to="/companies">
            ← Volver a empresas
          </Link>
        </div>
      </div>

      <div className="status-banner status-banner-info text-sm">
        Densidad de siembra recibe la ortofoto verificada, el Excel de coordenadas, un GeoPackage de exclusiones opcional y la densidad objetivo; después ejecuta el pipeline completo hasta mapas, archivos GIS e informe PDF.
      </div>
    </div>
  );
}
