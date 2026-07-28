import { useEffect, useState } from "react";
import { useLocation, useNavigate, Navigate } from "react-router-dom";
import api from "@/app/api";

export default function TemplatesCatalog() {
  const [rows, setRows] = useState<any[]>([]);
  const [activity, setActivity] = useState("");

  const navigate = useNavigate();
  const { search } = useLocation();
  const qs = new URLSearchParams(search);
  const companyId = qs.get("companyId");   // ej. "4"
  const preCode   = qs.get("code");        // ej. "RHS-01"

  // [TemplatesCatalog.tsx] dentro del componente

  // 2) Carga/filtrado del catálogo (solo por actividad)
  useEffect(() => {
    (async () => {
      const params: Record<string, any> = {};
      if (activity) params.activity = activity.trim();

      const data = await api.get(
        "/api/v1/templates",
        Object.keys(params).length ? { params } : undefined
      );
      setRows(Array.isArray(data) ? data : []);
    })().catch(console.error);
  }, [activity]);

  if (preCode && companyId) {
    return <Navigate to={`/companies/${companyId}/documents/new/${preCode}`} replace />;
  }
  
  return (
    <div>
      <h2>Plantillas</h2>

      <div className="mb-3">
        <input
          className="input"
          placeholder="Filtrar por actividad (BANANERA, CAMARONERA, ...)"
          value={activity}
          onChange={e => setActivity(e.target.value)}
        />
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Actividad</th>
            <th>Código</th>
            <th>Título</th>
            <th>Versión</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id ?? r.code}>
              <td>{r.activity}</td>
              <td>{r.code}</td>
              <td>{r.title}</td>
              <td>{r.version}</td>
              <td>
                {companyId && (
                  <button
                    className="btn btn-primary"
                    onClick={() => navigate(`/companies/${companyId}/documents/new/${r.code}`)}
                  >
                    Crear
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                No se encontraron plantillas con los filtros actuales.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
