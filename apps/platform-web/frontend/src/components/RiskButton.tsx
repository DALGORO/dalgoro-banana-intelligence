import React from "react";

type Level = "BAJO" | "MEDIO" | "ALTO" | null | undefined;

// Paletas con Tailwind (suaves, elegantes)
const PALETTE: Record<Exclude<Level, null | undefined> | "DEFAULT", {
  wrap: string; dot: string; text: string;
}> = {
  BAJO:   { wrap: "bg-emerald-500/10 ring-emerald-500/30", dot: "bg-emerald-400", text: "text-emerald-300" },
  MEDIO:  { wrap: "bg-amber-500/10 ring-amber-500/30",     dot: "bg-amber-400",  text: "text-amber-300"  },
  ALTO:   { wrap: "bg-rose-500/10 ring-rose-500/30",       dot: "bg-rose-400",   text: "text-rose-300"   },
  DEFAULT:{ wrap: "bg-slate-500/10 ring-slate-500/30",     dot: "bg-slate-400",  text: "text-slate-300"  },
};

export default function RiskButton({ level }: { level: Level }) {
  const p = (level && PALETTE[level]) || PALETTE.DEFAULT;
  const label = level ? (level[0] + level.slice(1).toLowerCase()) : "—"; // Bajo/Medio/Alto o —
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm ring-1 ${p.wrap} ${p.text}`}
      aria-label={`Riesgo ${label}`}
    >
      <span className={`h-2.5 w-2.5 rounded-full ${p.dot}`} />
      <span className="font-medium tracking-wide">{label}</span>
    </span>
  );
}
