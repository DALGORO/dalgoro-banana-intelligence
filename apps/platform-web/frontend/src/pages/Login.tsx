import { useNavigate } from "react-router-dom";
import { type FormEvent, useState } from "react";
import { login } from "../app/auth";

export default function Login(){
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string|undefined>();

  async function onSubmit(e: FormEvent){
    e.preventDefault();
    setErr(undefined); setLoading(true);
    try {
      await login(email, password);
      nav("/", { replace: true, state: { welcome: true, userEmail: email } });

    } catch (e:any) {
      setErr(e?.response?.data?.detail ?? "Credenciales inválidas");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--dal-bg-light)] px-4 dark:bg-[var(--dal-navy-900)]">
      <form onSubmit={onSubmit} className="card w-full max-w-md space-y-4">
        <div className="flex items-center gap-3">
          <img
            src="/logo-white.png"
            className="h-10 rounded-xl bg-[var(--dal-navy-900)] p-1 dark:bg-transparent"
          />
          <div>
            <div className="text-lg font-semibold text-slate-900 dark:text-white">
              DALGORO
            </div>
            <div className="text-sm text-slate-500 dark:text-slate-400">
              Acceso a la plataforma
            </div>
          </div>
        </div>

        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">
            Ingresar
          </h1>
          <p className="page-subtitle mt-1">
            Accede con tu correo y contraseña para continuar.
          </p>
        </div>

        {err && (
          <div className="status-banner status-banner-danger text-sm">
            {err}
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Correo
          </label>
          <input
            className="w-full"
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Contraseña
          </label>
          <input
            className="w-full"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </div>

        <button className="btn-primary w-full disabled:opacity-50" disabled={loading}>
          {loading ? "Ingresando..." : "Entrar"}
        </button>

        <div className="pt-1 text-center text-sm text-slate-600 dark:text-slate-300">
          ¿No tienes cuenta?
          <button
            type="button"
            onClick={() => nav("/signup")}
            className="ml-2 font-medium underline underline-offset-2 text-[var(--dal-copper-strong)] hover:opacity-90 dark:text-[#d6a07b]"
          >
            Crear cuenta
          </button>
        </div>
      </form>
    </div>
  );
}
