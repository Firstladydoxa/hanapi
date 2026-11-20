import type { Warning } from "@/lib/api";

const TYPE_LABEL: Record<Warning["type"], string> = {
  number: "Numbers", terminology: "Terminology", name: "Names", consistency: "Consistency", format: "Formatting", readiness: "Language pair",
};

/** Renders only the whitelisted warning fields (type, severity, message). */
export function Warnings({ warnings, emptyText }: { warnings: Warning[]; emptyText?: string }) {
  if (warnings.length === 0) {
    return <p className="text-xs text-ok-text">{emptyText ?? "No basic issues found. Please still review meaning, tone and context."}</p>;
  }
  return (
    <ul className="space-y-1.5 text-xs">
      {warnings.map((w, i) => (
        <li key={`${w.type}-${i}`} className={`rounded-md px-2.5 py-1.5 ${w.severity === "warning" ? "bg-warn/15 text-warn-text" : "bg-info/15 text-info-text"}`}>
          <span className="font-bold">{TYPE_LABEL[w.type] ?? w.type}: </span>
          {w.message}
        </li>
      ))}
    </ul>
  );
}
