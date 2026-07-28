// src/components/CompanyEditModal.tsx
import { useEffect, useState } from "react";
import { api } from "../app/api";

const ACTIVIDADES = [
  "BANANERA",
  "CAMARONERA",
  "MINERIA",
  "AGRICOLA",
  "GANADERA",
  "PESQUERA",
  "CONSTRUCCION",
  "SERVICIOS",
  "INDUSTRIA",
  "GENERICO",
];

type Company = {
  id: number;
  ruc: string;
  nombre?: string;
  name?: string;
  actividad?: string;
  riesgo?: string;
  trabajadores?: number;
};

type Props = {
  open: boolean;
  company: Company | null;
  onClose: () => void;
  onSaved: (updated: Company) => void;
};

export default function CompanyEditModal({ open, company, onClose, onSaved }: Props) {
  const [ruc, setRuc] = useState("");
  const [nombre, setNombre] = useState("");
  const [actividad, setActividad] = useState("");
  const [riesgo, setRiesgo] = useState<string>("");
  const [trabajadores, setTrabajadores] = useState<number | string>(0);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  
  useEffect(() => {
    if (!open || !company) return;

    const hydrate = (data: any) => {
        setRuc(data?.ruc ?? "");
        setNombre(data?.nombre ?? data?.name ?? "");
        setActividad((data?.actividad ?? "").toString().toUpperCase());
        setRiesgo((data?.riesgo ?? "").toString().toUpperCase());
        setTrabajadores(
        typeof data?.trabajadores === "number" ? data.trabajadores :
        Number.isFinite(parseInt(String(data?.trabajadores))) ? parseInt(String(data?.trabajadores)) :
        0
        );
        setErr(null);
    };

    // Pre-llenado instantáneo con lo que viene en la lista
    hydrate(company);

    // Sobre-escribe con el detalle más reciente del backend
    (async () => {
        try {
        const { data } = await api.get(`/api/v1/companies/${company.id}`);
        hydrate(data);
        } catch {
        /* ignora: si falla, te quedas con lo ya precargado */
        }
    })();
    }, [open, company?.id]);


  if (!open || !company) return null;

  const companyId = company.id;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);

    try {
      const payload: any = {
        ruc: (ruc || "").trim(),                  // ← NUEVO
        nombre: nombre.trim(),
        actividad: actividad.trim(),
        riesgo: (riesgo || "").toString().toUpperCase(),
        trabajadores: Number(trabajadores || 0),
      };
      const { data } = await api.put(`/api/v1/companies/${companyId}`, payload);
      onSaved(data);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? "No se pudo guardar los cambios.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4">
      <div className="card w-full max-w-xl">
        <div className="section-head border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
              Editar empresa
            </h2>
            <p className="page-subtitle mt-1">
              Actualiza los datos base sin alterar la lógica documental ni la configuración general.
            </p>
          </div>

          <button
            onClick={onClose}
            className="btn-ghost px-3 py-2"
            type="button"
            aria-label="Cerrar modal"
          >
            ✕
          </button>
        </div>

        <form onSubmit={onSubmit} className="p-5 space-y-4">
          {err && (
            <div className="status-banner status-banner-danger text-sm">
              {err}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">RUC</span>
              <input
                value={ruc}
                onChange={e => setRuc(e.target.value)}
                required
                minLength={10}
                maxLength={13}
                className="mt-1 w-full"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Nombre (razón social)
              </span>
              <input
                value={nombre}
                onChange={e => setNombre(e.target.value)}
                required
                className="mt-1 w-full"
              />
            </label>

            <label className="block md:col-span-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Actividad</span>
              <select
                value={actividad}
                onChange={e => setActividad(e.target.value)}
                required
                className="mt-1 w-full"
              >
                <option value="">Selecciona…</option>
                {ACTIVIDADES.map(act => (
                  <option key={act} value={act}>{act}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Riesgo</span>
              <select
                value={riesgo}
                onChange={e => setRiesgo(e.target.value)}
                className="mt-1 w-full"
              >
                <option value="">(sin definir)</option>
                <option value="BAJO">BAJO</option>
                <option value="MEDIO">MEDIO</option>
                <option value="ALTO">ALTO</option>
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Trabajadores</span>
              <input
                type="number"
                min={0}
                value={trabajadores}
                onChange={e => {
                  const v = e.currentTarget.value;
                  if (v === "") { setTrabajadores(""); return; }
                  const n = Number(v);
                  setTrabajadores(Number.isFinite(n) ? n : 0);
                }}
                className="mt-1 w-full"
              />
            </label>
          </div>

          <div className="flex justify-end gap-2 pt-2 flex-wrap">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              Cancelar
            </button>

            <button
              type="submit"
              disabled={saving}
              className="btn-primary disabled:opacity-60"
            >
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
