import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../app/api";

export default function Signup() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [accept, setAccept] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showTerms, setShowTerms] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);

    if (!email.trim() || !pwd || !pwd2) {
      setErr("Completa todos los campos.");
      return;
    }
    if (pwd !== pwd2) {
      setErr("Las contraseñas no coinciden.");
      return;
    }
    if (!accept) {
      setErr("Debes aceptar la autorización de uso de datos.");
      return;
    }

    try {
      setLoading(true);
      // Endpoint previsto por backend para alta pública
      await api.post("/api/v1/auth/register", {
        email: email.trim(),
        password: pwd,
      });
      alert("Cuenta creada. Revisa tu correo de bienvenida.");
      navigate("/login");
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? "No se pudo crear la cuenta.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--dal-bg-light)] px-4 dark:bg-[var(--dal-navy-900)]">
      <div className="card w-full max-w-md">
        <div className="mb-5 flex items-center gap-3">
          <img src="/logo-white.png" className="h-10 rounded-xl bg-[var(--dal-navy-900)] p-1 dark:bg-transparent" />
          <div>
            <div className="text-lg font-semibold text-slate-900 dark:text-white">DALGORO</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">
              Registro de acceso a la plataforma
            </div>
          </div>
        </div>

        <div className="mb-4">
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">Crear cuenta</h1>
          <p className="page-subtitle mt-1">
            Completa tus datos para crear un usuario y acceder al sistema.
          </p>
        </div>

        {err && (
          <div className="status-banner status-banner-danger mb-4 text-sm">
            {err}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Correo electrónico
            </label>
            <input
              type="email"
              placeholder="tucorreo@empresa.com"
              className="w-full"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Contraseña
            </label>
            <input
              type="password"
              placeholder="Ingresa tu contraseña"
              className="w-full"
              value={pwd}
              onChange={(e) => setPwd(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Repite la contraseña
            </label>
            <input
              type="password"
              placeholder="Confirma tu contraseña"
              className="w-full"
              value={pwd2}
              onChange={(e) => setPwd2(e.target.value)}
            />
          </div>

          <label className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300">
            <input
              id="accept"
              type="checkbox"
              className="mt-1"
              checked={accept}
              onChange={(e) => setAccept(e.target.checked)}
            />
            <span>
              Acepto la{" "}
              <button
                type="button"
                className="font-medium underline underline-offset-2 text-[var(--dal-copper-strong)] dark:text-[#d6a07b]"
                onClick={() => setShowTerms(true)}
              >
                autorización de uso de datos
              </button>.
            </span>
          </label>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full disabled:opacity-60"
          >
            {loading ? "Creando…" : "Crear usuario"}
          </button>

          <div className="pt-1 text-center text-sm text-slate-600 dark:text-slate-300">
            ¿Ya tienes cuenta?{" "}
            <button
              type="button"
              onClick={() => navigate("/login")}
              className="font-medium underline underline-offset-2 text-[var(--dal-copper-strong)] hover:opacity-90 dark:text-[#d6a07b]"
            >
              Ingresar
            </button>
          </div>
        </form>
      </div>

      {showTerms && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4">
          <div className="card w-full max-w-lg">
            <div className="section-head border-b border-slate-200 px-5 py-4 dark:border-white/10">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  Autorización de uso de datos
                </h2>
                <p className="page-subtitle mt-1">
                  Revisa esta autorización antes de completar el registro.
                </p>
              </div>
            </div>

            <div className="p-5">
              <div className="max-h-64 overflow-auto space-y-3 text-sm text-slate-700 dark:text-slate-300">
                <p>
                  Autorizo a DALGORO a tratar los datos personales que ingreso en
                  el sistema para operar la plataforma y prestar los servicios,
                  conforme a normativa y política de privacidad.
                </p>
                <p>
                  Puedo revocar esta autorización ejerciendo mis derechos a través
                  de los canales habilitados.
                </p>
              </div>

              <div className="mt-5 flex justify-end gap-2 flex-wrap">
                <button
                  className="btn-secondary"
                  onClick={() => setShowTerms(false)}
                  type="button"
                >
                  Cerrar
                </button>

                <button
                  className="btn-primary"
                  onClick={() => {
                    setAccept(true);
                    setShowTerms(false);
                  }}
                  type="button"
                >
                  Acepto
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
