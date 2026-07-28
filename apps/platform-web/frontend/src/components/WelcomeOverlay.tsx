type Props = {
  open: boolean;
  onClose: () => void;
  userEmail?: string | null;
};

export default function WelcomeOverlay({ open, onClose, userEmail }: Props) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 backdrop-blur-md p-4">
      <div className="relative w-full max-w-5xl overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-2xl dark:border-white/10 dark:bg-[var(--dal-navy-900)]">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-20 -left-16 h-56 w-56 rounded-full bg-emerald-300/25 blur-3xl dark:bg-emerald-500/10" />
          <div className="absolute top-8 right-0 h-64 w-64 rounded-full bg-[var(--dal-copper)]/20 blur-3xl dark:bg-[var(--dal-copper)]/10" />
          <div className="absolute bottom-0 left-1/3 h-48 w-48 rounded-full bg-sky-300/20 blur-3xl dark:bg-sky-500/10" />
        </div>

        <div className="relative grid gap-0 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="p-6 md:p-8 lg:p-10">            
            <div className="mt-5 flex items-start gap-4">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-3xl border border-emerald-200 bg-emerald-100 text-emerald-700 shadow-sm dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200">
                <svg
                  viewBox="0 0 24 24"
                  className="h-8 w-8"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path d="M12 2c3.87 0 7 3.13 7 7v2.5h1a2 2 0 0 1 2 2V16a2 2 0 0 1-2 2h-1v1a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-1H4a2 2 0 0 1-2-2v-2.5a2 2 0 0 1 2-2h1V9c0-3.87 3.13-7 7-7Zm-1 9H6.5V9a5.5 5.5 0 0 1 11 0v2H13V7h-2v4Z" />
                </svg>
              </div>

              <div>
                <h2 className="text-3xl font-semibold tracking-tight text-slate-900 dark:text-white md:text-4xl">
                  Bienvenido{userEmail ? `, ${userEmail}` : ""}
                </h2>

                <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600 dark:text-slate-300 md:text-base">
                  Ya estás dentro de <span className="font-semibold text-slate-900 dark:text-white">DALGORO SST Compliance</span>.
                  Desde aquí podrás organizar empresas, generar documentación y detectar alertas críticas de cumplimiento
                  con una experiencia mucho más clara y guiada.
                </p>
              </div>
            </div>

            <div className="mt-8 grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--dal-navy-900)] text-white dark:bg-white/10">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                    <path d="M4 5a2 2 0 0 1 2-2h4.5a2 2 0 0 1 1.6.8l1.2 1.6A2 2 0 0 0 14.9 6H18a2 2 0 0 1 2 2v1H4V5Zm0 5h16v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7Z" />
                  </svg>
                </div>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                  Empresas centralizadas
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Revisa actividad, riesgo, trabajadores y estado documental desde una sola vista.
                </p>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--dal-copper-strong)] text-white">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                    <path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm7 1.5V9h4.5" />
                  </svg>
                </div>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                  Documentos bajo control
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Genera, consulta y organiza soportes documentales con mejor trazabilidad.
                </p>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-500 text-white">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                    <path d="M12 3 2 20h20L12 3Zm1 5v5h-2V8h2Zm0 8v2h-2v-2h2Z" />
                  </svg>
                </div>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                  Alertas prioritarias
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Detecta vencimientos, próximos cumplimientos y prioridades operativas.
                </p>
              </div>
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <button
                onClick={onClose}
                className="btn-primary px-6"
                type="button"
              >
                Comenzar
              </button>

              <button
                onClick={onClose}
                className="btn-secondary"
                type="button"
              >
                Omitir bienvenida
              </button>
            </div>
          </div>

          <div className="border-t border-slate-200 bg-slate-50/80 p-6 dark:border-white/10 dark:bg-[#14262b] lg:border-l lg:border-t-0 lg:p-8">
            <div className="eyebrow mb-3">Inicio recomendado</div>

            <h3 className="text-xl font-semibold text-slate-900 dark:text-white">
              Empieza por este recorrido
            </h3>

            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              Esta secuencia te ayuda a entrar al sistema con claridad y aprovechar mejor el flujo de trabajo.
            </p>

            <div className="mt-6 space-y-3">
              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white dark:bg-white/10">
                    1
                  </div>
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">Revisa tus empresas</p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                      Verifica actividad, riesgo y número de trabajadores antes de generar documentos.
                    </p>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white dark:bg-white/10">
                    2
                  </div>
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">Prioriza requisitos</p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                      Identifica qué está vencido, qué está próximo y qué documento conviene generar primero.
                    </p>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white dark:bg-white/10">
                    3
                  </div>
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">Genera y da seguimiento</p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                      Usa el módulo documental para generar soportes y mantener trazabilidad de cumplimiento.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">
              Consejo: comienza revisando tus empresas registradas. Desde ahí podrás ver su información, consultar documentos y detectar qué temas requieren atención primero.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
