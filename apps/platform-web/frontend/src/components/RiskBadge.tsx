type Level = "BAJO" | "MEDIO" | "ALTO" | null | undefined;

const COLORS: Record<Exclude<Level, null | undefined> | "DEFAULT", string> = {
  BAJO: "bg-green-500",
  MEDIO: "bg-yellow-500",
  ALTO: "bg-red-500",
  DEFAULT: "bg-gray-400",
};

export default function RiskBadge({ level }: { level: Level }) {
  const color =
    level && (COLORS[level] as string) ? COLORS[level] : COLORS.DEFAULT;
  const label = level ?? "—";

  return (
    <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 ring-1 ring-white/10">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      <span className="text-sm">{label}</span>
    </span>
  );
}
