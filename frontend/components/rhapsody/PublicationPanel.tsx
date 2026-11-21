"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type PublicationState } from "@/lib/api";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function PublicationPanel({ assignmentId, status }: { assignmentId: string; status: string }) {
  const [state, setState] = useState<PublicationState | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const eligible = ["approved", "published", "changes_requested"].includes(status);
  const load = useCallback(async () => { try { setState(await api.publishing.publication(assignmentId)); } catch { setState(null); } }, [assignmentId]);
  useEffect(() => { if (eligible) void load(); }, [eligible, load]);
  if (!eligible) return null;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ kind: "success", text: ok }); await load(); } catch (x) { setMsg({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  const proof = state?.proof;
  return (
    <div className="mt-2 rounded border p-2 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">Proofing: {(state?.assignment_status ?? status).replace("_", " ")}</span>
        <button className="btn btn-secondary min-h-[30px] px-2 py-0.5 text-xs" disabled={busy}
          onClick={() => void run(async () => { const p = await api.publishing.createProof(assignmentId); await api.publishing.renderProof(p.id); }, "New proof PDF generated.")}>Generate proof PDF</button>
        {proof ? <a className="underline" href={api.publishing.proofUrl(proof.id)} target="_blank" rel="noreferrer">Open proof (profile rev. {proof.profile_version})</a> : null}
        {proof?.stale ? <span className="text-amber-700">The translation changed after this proof.</span> : null}
      </div>
      {proof ? (<div className="flex flex-wrap items-center gap-2">
        <input className="input min-h-[30px] flex-1 text-xs" placeholder="Note for the translator (required to return for changes)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn btn-primary min-h-[30px] px-2 py-0.5 text-xs" disabled={busy || proof.stale} onClick={() => void run(() => api.publishing.approvePublication(assignmentId, note || undefined), "Approved for publication.")}>Approve for publication</button>
        <button className="btn btn-secondary min-h-[30px] px-2 py-0.5 text-xs" disabled={busy || !note.trim()} onClick={() => void run(() => api.publishing.requestChanges(assignmentId, note), "Returned for changes.")}>Return for changes</button>
      </div>) : null}
      {msg ? <p className={msg.kind === "error" ? "text-red-700" : "text-green-700"}>{msg.text}</p> : null}
      {state?.history.length ? (<ul className="text-ink-muted">{state.history.slice(0, 3).map((h) => (
        <li key={h.created_at}>{h.decision.replace("_", " ")} by {h.by} (rev. {h.profile_version}){h.note ? ` — ${h.note}` : ""}</li>))}</ul>) : null}
    </div>
  );
}
