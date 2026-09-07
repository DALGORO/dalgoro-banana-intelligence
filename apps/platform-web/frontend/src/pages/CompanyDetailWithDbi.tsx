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
            Continúa al módulo agrícola para crear fincas y lotes, importar coordenadas, cargar ortofotos GeoTIFF y preparar INSPECT para el iPad.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          {id && (
            <Link className="btn-primary" to={`/companies/${id}/agricultura`}>
              Abrir análisis geoespacial
            </Link>
          )}
          <Link className="btn-ghost" to="/companies">
            ← Volver a empresas
          </Link>
        </div>
      </div>

      <div className="status-banner status-banner-info text-sm">
        El flujo visible de esta instalación está enfocado en empresa → finca → lote → GeoJSON → ortofoto → inspección de campo.
      </div>
    </div>
  );
}
