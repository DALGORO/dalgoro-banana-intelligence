import { AnimatePresence, motion } from "framer-motion";

export default function SuccessModal({
  open, onClose, message="Registrado correctamente"
}: { open:boolean; onClose:()=>void; message?:string }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={onClose}
        >
          <motion.div
            onMouseDown={(e) => e.stopPropagation()}
            className="card w-full max-w-md text-center space-y-4 p-8"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 22 }}
          >
            <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-full border border-emerald-200 bg-emerald-100 text-5xl font-bold text-emerald-700 shadow-sm dark:border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-200">
              ✓
            </div>

            <div>
              <h3 className="text-2xl font-semibold text-slate-900 dark:text-white">
                Operación completada
              </h3>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                {message}
              </p>
            </div>

            <div className="pt-2">
              <button
                onClick={onClose}
                className="btn-primary"
                type="button"
              >
                Aceptar
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
