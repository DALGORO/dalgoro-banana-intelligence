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
        <div className="relative grid gap-0 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="p-6 md:p-8 lg:p-10">
            <div className="flex items-start gap-4">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-3xl border border-emerald-200 bg-emerald-100 text-emerald-700 shadow-sm dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200">
                <svg viewBox="0 0 24 24" className="h-8 w-8" fill="currentColor" aria-hidden="true">
                  <path d="M12 2 3 7v10l9 5 9-5V7l-9-5Zm0 2.3 6.8 3.8L12 12 5.2 8.1 12 4.3Zm-7 5.5 6 3.4v6.1l-6-3.4V9.8Zm8 9.5v-6.1l6-3.4v6.1l-6 3.4Z" />
                </svg>
              </div>

              <div>
                <h2 className="text-3xl font-semibold tracking-tight text-slate-900 dark:text-white md:text-4xl">
                  Bienvenido{userEmail ? `, ${userEmail}` : ""}
                </h2>
                <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600 dark:text-slate-300 md:text-base">
                  Ya estás dentro de <span className="font-semibold text-slate-900 dark:text-white">DALGORO Banana Intelligence – sistema geoespacial</span>.
                  Desde aquí podrás organizar empresas, fincas y lotes, cargar ortofotos y realizar inspecciones de campo desde el iPad.
                </p>
              </div>
            </div>

            <div className="mt-8 grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Empresas y fincas</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Organiza cada cliente, crea sus fincas y estructura los lotes que formarán parte del análisis.
                </p>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Información geoespacial</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Importa límites GeoJSON y carga ortofotos GeoTIFF manteniendo su referencia espacial.
                </p>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-white/10 dark:bg-white/[0.04]">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Inspección de campo</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  Abre INSPECT en el iPad, captura GPS y sincroniza observaciones incluso después de trabajar sin conexión.
                </p>
              </div>
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <button onClick={onClose} className="btn-primary px-6" type="button">
                Comenzar
              </button>
              <button onClick={onClose} className="btn-secondary" type="button">
                Omitir bienvenida
              </button>
            </div>
          </div>

          <div className="border-t border-slate-200 bg-slate-50/80 p-6 dark:border-white/10 dark:bg-[#14262b] lg:border-l lg:border-t-0 lg:p-8">
            <div className="eyebrow mb-3">Inicio recomendado</div>
            <h3 className="text-xl font-semibold text-slate-900 dark:text-white">Primera prueba geoespacial</h3>
            <div className="mt-6 space-y-3 text-sm text-slate-700 dark:text-slate-300">
              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <strong>1. Selecciona o crea una empresa.</strong>
                <p className="mt-1">Será el contenedor principal de la información geoespacial.</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <strong>2. Crea finca y lote.</strong>
                <p className="mt-1">Importa el límite del lote en GeoJSON EPSG:4326.</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-[#0f1d21]">
                <strong>3. Carga la ortofoto y abre INSPECT.</strong>
                <p className="mt-1">Completa la carga desde la laptop y usa el enlace de campo en el iPad.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
