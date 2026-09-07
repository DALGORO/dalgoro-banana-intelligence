import { Link, useParams } from "react-router-dom";

import CompanyDetail from "./CompanyDetail";

export default function CompanyDetailWithDbi() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-4">
      <div className="status-banner status-banner-info">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-medium">Agricultura DBI · primera prueba real</div>
            <p className="mt-1 text-sm">
              Crea finca y lote, importa el límite GeoJSON, carga la ortofoto GeoTIFF y genera el enlace INSPECT para usarlo desde el iPad.
            </p>
          </div>
          {id && (
            <Link className="btn-primary" to={`/companies/${id}/agricultura`}>
              Abrir módulo agrícola
            </Link>
          )}
        </div>
      </div>

      <CompanyDetail />
    </div>
  );
}
