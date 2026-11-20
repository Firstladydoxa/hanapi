"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type ChatActionOut } from "@/lib/api";

interface Msg { id: number; role: "user" | "han"; text: string; actions?: ChatActionOut[]; file?: string }

const ADMIN_STARTERS = ["Han, start the layout of Rhapsody for the month of November 2026 using the word document I uploaded"];
const TRANSLATOR_STARTERS = ["Han, start the translation of Rhapsody in French for the month of November"];
const ERR = "I'm sorry, I couldn't complete that just now. Please try again shortly.";
const DOCX = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function RhapsodyChat({ admin, onChanged }: { admin: boolean; onChanged?: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const seq = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const add = (m: Omit<Msg, "id">) => setMsgs((x) => [...x, { ...m, id: ++seq.current }]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [msgs, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    const attached = file;
    setBusy(true); setInput(""); setFile(null);
    add({ role: "user", text: message, file: attached?.name });
    try {
      if (attached) {
        const f = new FormData();
        f.append("file", attached); f.append("message", message);
        const up = await api.rhapsody.chatAttachment(f);
        add({ role: "han", text: `Received "${up.filename}" and filed it under ${up.edition_title}.` });
      }
      let id = convId;
      if (!id) { id = (await api.conversations.create()).id; setConvId(id); }
      const r = await api.conversations.send(id, { message });
      add({ role: "han", text: r.reply, actions: r.actions });
      onChanged?.();
    } catch (e) {
      add({ role: "han", text: e instanceof ApiError ? e.message : ERR });
    } finally { setBusy(false); }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void send(input); };
  const starters = admin ? ADMIN_STARTERS : TRANSLATOR_STARTERS;

  return (
    <section className="card space-y-3" aria-label="Chat with HAN about Rhapsody">
      <h2 className="text-sm font-semibold">Chat with HAN</h2>
      <div className="max-h-[50vh] min-h-[120px] space-y-3 overflow-y-auto" role="log" aria-live="polite">
        {msgs.length === 0 ? (
          <div className="space-y-2 text-sm text-ink-muted">
            <p>{admin ? "Attach the month's Word manuscript with the + button and ask me to lay it out." : "Ask me to open a Rhapsody month in your language and I'll draft each paragraph for you to review."}</p>
            {starters.map((s) => <button key={s} type="button" className="block rounded-xl border border-line px-3 py-2 text-left hover:border-brand" onClick={() => setInput(s)}>{s}</button>)}
          </div>
        ) : msgs.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : ""}>
            <div className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-2xl border px-3 py-2 text-left text-sm ${m.role === "user" ? "border-brand bg-brand/10" : "border-line"}`}>
              {m.file ? <p className="mb-1 text-xs text-ink-muted">📎 {m.file}</p> : null}
              {m.text}
              {m.actions?.filter((a) => a.type === "open_rhapsody" && a.path).map((a) => (
                <Link key={a.path} href={a.path as string} className="btn btn-primary mt-2 block min-h-[34px] px-3 py-1 text-center text-xs">{a.label ?? "Open"}</Link>
              ))}
            </div>
          </div>
        ))}
        {busy ? <p className="text-xs text-ink-muted">HAN is working…</p> : null}
        <div ref={bottom} />
      </div>
      {file ? <p className="text-xs">📎 {file.name} <button type="button" className="underline" onClick={() => setFile(null)}>remove</button></p> : null}
      <form className="flex items-end gap-2" onSubmit={submit}>
        {admin ? (
          <>
            <input ref={picker} type="file" accept={DOCX} className="hidden" aria-label="Attach Word document" onChange={(e) => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
            <button type="button" className="btn min-h-[44px] px-4 text-lg" aria-label="Attach Word document" title="Attach the Word manuscript" onClick={() => picker.current?.click()}>+</button>
          </>
        ) : null}
        <label className="sr-only" htmlFor="rhapsody-chat">Message HAN</label>
        <textarea id="rhapsody-chat" className="input min-h-[44px] flex-1" rows={1} value={input} placeholder="Message HAN…" maxLength={2000}
          onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
        <button type="submit" className="btn btn-primary min-h-[44px] px-5" disabled={busy || !input.trim()}>Send</button>
      </form>
    </section>
  );
}
