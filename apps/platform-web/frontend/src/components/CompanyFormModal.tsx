import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../app/api";

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess: (company: any) => void;
  quotaBlocked?: boolean;
  quotaText?: string;
};

type Form = {
  ruc: string;
  nombre: string;
  // Catálogo cerrado (8 actividades). Mantener "MINERIA" sin tilde por compatibilidad.
  actividad:
    | "BANANERA"
    | "CAMARONERA"
    | "GRANJA PORCINA"
    | "GRANJA AVÍCOLA"   // puede venir desde UI con tilde; el backend normaliza
    | "MINERIA"
    | "HOTEL/ALOJAMIENTO"
    | "RESTAURANTE"
    | "OTROS";
  trabajadores: number;
  riesgo: "BAJO" | "MEDIO" | "ALTO";
};


const initial: Form = {
  ruc: "",
  nombre: "",
  actividad: "BANANERA",
  trabajadores: 0,
  riesgo: "MEDIO",
};

export default function CompanyFormModal({
  open,
  onClose,
  onSuccess,
  quotaBlocked = false,
  quotaText,
}: Props) {
  const [f, setF] = useState<Form>(initial);
  const [busy, setBusy] = useState(false);
  const [errField, setErrField] = useState<Partial<Record<keyof Form, string>>>({});
  const [errGeneral, setErrGeneral] = useState<string | undefined>();

  useEffect(() => {
    if (!open) {
      setF(initial);
      setBusy(false);
      setErrField({});
      setErrGeneral(undefined);
    }
  }, [open]);

  const validate = () => {
    const e: Partial<Record<keyof Form, string>> = {};
    if (!/^\d{13}$/.test(f.ruc)) e.ruc = "El RUC debe tener 13 dígitos.";
    if (!f.nombre.trim()) e.nombre = "Campo obligatorio";
    if (f.trabajadores < 0) e.trabajadores = "No puede ser negativo";
    setErrField(e);
    return Object.keys(e).length === 0;
  };

  const submit = async () => {
    if (quotaBlocked) {
      setErrGeneral(quotaText || "Cupo agotado. Amplía tu plan para crear más empresas.");
      return;
    }

    if (!validate()) return;
    setBusy(true);
    setErrGeneral(undefined);
    try {
      // El backend espera estos nombres en español: ruc, nombre, actividad, trabajadores, riesgo
      const { data } = await api.post("/api/v1/companies", {
        ruc: f.ruc,
        nombre: f.nombre,
        actividad: f.actividad,
        trabajadores: f.trabajadores,
        riesgo: f.riesgo,
      });

      onClose();
      onSuccess(data); // Companies.tsx abrirá el SuccessModal y añadirá la empresa a la lista
    } catch (e: any) {
      const msg = e?.response?.data?.detail || "Error al registrar";
      // Si el backend devuelve 400 por RUC duplicado o 403 por cupo, lo mostramos claramente
      if (String(msg).toLowerCase().includes("ruc")) {
        setErrField((prev) => ({ ...prev, ruc: msg }));
      } else {
        setErrGeneral(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4">
          <motion.div
            initial={{ scale: 0.85, y: -12, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 22 }}
            className="card w-[640px] max-w-[92vw]"
          >
            <div className="section-head border-b border-slate-200 px-5 py-4 dark:border-white/10">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  Nueva empresa
                </h2>
                <p className="page-subtitle mt-1">
                  Registra una nueva empresa usando los datos base requeridos por el sistema.
                </p>
              </div>

              <button
                type="button"
                onClick={onClose}
                className="btn-ghost px-3 py-2"
                aria-label="Cerrar modal"
              >
                ✕
              </button>
            </div>

            <div className="p-5 space-y-4">
              {errGeneral && (
                <div className="status-banner status-banner-danger text-sm">
                  {errGeneral}
                </div>
              )}

              {quotaText && (
                <div
                  className={`text-sm ${
                    quotaBlocked
                      ? "status-banner status-banner-warning"
                      : "status-banner status-banner-info"
                  }`}
                >
                  {quotaText}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  RUC
                </label>
                <input
                  className={`w-full ${errField.ruc ? "border-red-500 dark:border-red-400" : ""}`}
                  type="text"
                  inputMode="numeric"
                  maxLength={13}
                  placeholder="13 dígitos"
                  value={f.ruc}
                  onChange={(e) =>
                    setF((s) => ({ ...s, ruc: e.target.value.replace(/\D/g, "") }))
                  }
                />
                {errField.ruc && (
                  <p className="mt-1 text-sm text-red-600 dark:text-red-300">{errField.ruc}</p>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Nombre
                  </label>
                  <input
                    className={`w-full ${errField.nombre ? "border-red-500 dark:border-red-400" : ""}`}
                    value={f.nombre}
                    onChange={(e) => setF((s) => ({ ...s, nombre: e.target.value }))}
                  />
                  {errField.nombre && (
                    <p className="mt-1 text-sm text-red-600 dark:text-red-300">{errField.nombre}</p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Trabajadores
                  </label>
                  <input
                    className={`w-full ${errField.trabajadores ? "border-red-500 dark:border-red-400" : ""}`}
                    type="number"
                    min={0}
                    value={f.trabajadores}
                    onChange={(e) =>
                      setF((s) => ({
                        ...s,
                        trabajadores: Number.isNaN(+e.target.value)
                          ? 0
                          : parseInt(e.target.value || "0", 10),
                      }))
                    }
                  />
                  {errField.trabajadores && (
                    <p className="mt-1 text-sm text-red-600 dark:text-red-300">
                      {errField.trabajadores}
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Actividad
                  </label>
                  <select
                    className="w-full"
                    value={f.actividad}
                    onChange={(e) =>
                      setF((s) => ({ ...s, actividad: e.target.value as Form["actividad"] }))
                    }
                  >
                    {!([
                      "BANANERA",
                      "CAMARONERA",
                      "GRANJA PORCINA",
                      "GRANJA AVÍCOLA",
                      "MINERIA",
                      "HOTEL/ALOJAMIENTO",
                      "RESTAURANTE",
                      "OTROS",
                    ] as const).includes(f.actividad as any) && (
                      <option value={f.actividad}>{f.actividad} (LEGACY)</option>
                    )}

                    <option>BANANERA</option>
                    <option>CAMARONERA</option>
                    <option>GRANJA PORCINA</option>
                    <option>GRANJA AVÍCOLA</option>
                    <option>MINERIA</option>
                    <option>HOTEL/ALOJAMIENTO</option>
                    <option>RESTAURANTE</option>
                    <option>OTROS</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Riesgo
                  </label>
                  <select
                    className="w-full"
                    value={f.riesgo}
                    onChange={(e) =>
                      setF((s) => ({ ...s, riesgo: e.target.value as Form["riesgo"] }))
                    }
                  >
                    <option>BAJO</option>
                    <option>MEDIO</option>
                    <option>ALTO</option>
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2 flex-wrap">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={onClose}
                  disabled={busy}
                >
                  Cancelar
                </button>

                <button
                  type="button"
                  className="btn-primary disabled:opacity-60"
                  onClick={submit}
                  disabled={busy || quotaBlocked}
                >
                  {quotaBlocked ? "Cupo agotado" : busy ? "Registrando…" : "Registrar"}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}