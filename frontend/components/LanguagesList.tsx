"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Availability, type LanguageSupport } from "@/lib/api";
import { Alert, Spinner } from "./ui";

const LABEL: Record<Availability, string> = {
  enabled: "Available", enabled_with_review: "Available with review", controlled_testing: "Controlled testing", not_enabled: "Not yet enabled",
};
const STYLE: Record<Availability, string> = {
  enabled: "bg-ok/15 text-ok-text", enabled_with_review: "bg-info/15 text-info-text",
  controlled_testing: "bg-warn/15 text-warn-text", not_enabled: "bg-overlay/5 text-ink-muted",
};
const FILTERS: ("all" | Availability)[] = ["all", "enabled", "enabled_with_review", "controlled_testing", "not_enabled"];

export function LanguagesList() {
  const [rows, setRows] = useState<LanguageSupport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | Availability>("all");

  useEffect(() => { api.languageSupport().then(setRows).catch((e) => setError(e instanceof ApiError ? e.message : "Unable to load languages.")); }, []);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => (filter === "all" || r.availability === filter) && (!t || `${r.name} ${r.native_name ?? ""} ${r.code}`.toLowerCase().includes(t)));
  }, [rows, q, filter]);

  if (error) return <Alert>{error}</Alert>;
  if (!rows) return <Spinner label="Loading languages" />;
  return (
    <div className="space-y-4">
      <Alert kind="info">Languages in controlled testing produce experimental drafts that have not been validated by TNI. Always review them carefully; approval is always your decision.</Alert>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[220px] flex-1"><label className="label" htmlFor="lang-q">Search</label><input id="lang-q" className="input" placeholder="Name, native name or code" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div><label className="label" htmlFor="lang-f">Status</label>
          <select id="lang-f" className="input" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            {FILTERS.map((f) => <option key={f} value={f}>{f === "all" ? "All languages" : LABEL[f]}</option>)}
          </select></div>
      </div>
      <p className="text-xs text-ink-muted">{shown.length} of {rows.length} languages</p>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Language</th><th className="pr-4">Native name</th><th className="pr-4">Code</th><th>Status</th></tr></thead>
        <tbody>{shown.map((r) => (
          <tr key={r.code} className="border-t border-line">
            <td className="py-2 pr-4 font-semibold">{r.name}</td><td className="pr-4">{r.native_name ?? "—"}</td><td className="pr-4 font-mono text-xs">{r.code}</td>
            <td><span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold ${STYLE[r.availability]}`}>{LABEL[r.availability]}</span></td>
          </tr>))}</tbody></table></div>
    </div>
  );
}
