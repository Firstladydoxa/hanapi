"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type ChatMessageOut, type ConversationSummary, type ProjectDetail } from "@/lib/api";
import { Alert, Spinner } from "./ui";
import { ReviewPanel } from "./ReviewPanel";

const FALLBACK_STARTERS = ["Help me translate a text.", "Explain a difficult terminology choice.", "Review my translation.", "Explain how to use HAN."];
const ERR = "I'm sorry, I couldn't complete that just now. Please try again shortly.";

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString();
}

export function Chat({ project, onOpenWorkspace, about }: { project: ProjectDetail; onOpenWorkspace: (translationId: string) => void; about?: string | null }) {
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [view, setView] = useState<"active" | "archived">("active");
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [starters, setStarters] = useState<string[]>(FALLBACK_STARTERS);
  const [hasMore, setHasMore] = useState(false);
  const [title, setTitle] = useState("");
  const [archived, setArchived] = useState(false);
  const [input, setInput] = useState("");
  const [aboutId, setAboutId] = useState<string | null>(about ?? null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const scroll = () => setTimeout(() => bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }), 50);

  const refresh = useCallback(async (q = search, status = view) => {
    try { setList(await api.conversations.list({ project_id: project.id, q: q || undefined, status })); } catch { /* the list is a convenience */ }
  }, [project.id, search, view]);

  const open = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const c = await api.conversations.get(id);
      setActiveId(c.id); setMessages(c.messages); setHasMore(c.has_more_before); setTitle(c.title); setArchived(c.status === "archived");
      if (c.starters.length) setStarters(c.starters);
      setPanel(false);
      scroll();
    } catch (e) { setError(e instanceof ApiError ? e.message : ERR); } finally { setLoading(false); }
  }, []);

  const fresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const c = await api.conversations.create(project.id);
      setActiveId(c.id); setMessages(c.messages); setHasMore(false); setTitle(""); setArchived(false);
      if (c.starters.length) setStarters(c.starters);
      setPanel(false);
    } catch (e) { setError(e instanceof ApiError ? e.message : ERR); } finally { setLoading(false); }
  }, [project.id]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      const existing = await api.conversations.list({ project_id: project.id, status: "active", limit: 50 }).catch(() => []);
      setList(existing);
      // arriving from "Ask HAN about this" starts a clean conversation; otherwise continue the latest one
      if (existing[0] && !about) await open(existing[0].id); else await fresh();
    })();
  }, [project.id, about, open, fresh]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy || !activeId || archived) return;
    setError(null);
    setBusy(true);
    const local: ChatMessageOut = { id: `local-${Date.now()}`, seq: (messages.at(-1)?.seq ?? 0) + 1, role: "user", content: message, kind: "text", created_at: new Date().toISOString(), translation: null, clarification: null, actions: [], sources: [] };
    setMessages((m) => [...m, local]);
    setInput("");
    try {
      const r = await api.conversations.send(activeId, { message, context_translation_id: aboutId ?? undefined });
      const reply: ChatMessageOut = { id: r.message_id ?? `r-${Date.now()}`, seq: local.seq + 1, role: "assistant", content: r.reply, kind: r.translation ? "translation" : r.clarification ? "clarification" : "answer",
        created_at: new Date().toISOString(), translation: r.translation, clarification: r.clarification, actions: r.actions, sources: r.sources ?? [] };
      setMessages((m) => [...m, reply]);
      if (r.title) setTitle(r.title);
      void refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : ERR);
    } finally {
      setBusy(false);
      scroll();
    }
  }

  async function older() {
    const first = messages[0];
    if (!activeId || !first) return;
    const page = await api.conversations.older(activeId, first.seq).catch(() => null);
    if (page) { setMessages((m) => [...page.messages, ...m]); setHasMore(page.has_more_before); }
  }

  async function rename(id: string, name: string) {
    setRenaming(null);
    if (!name.trim()) return;
    try { await api.conversations.patch(id, { title: name.trim() }); if (id === activeId) setTitle(name.trim()); void refresh(); } catch (e) { setError(e instanceof ApiError ? e.message : ERR); }
  }
  async function setStatus(id: string, status: "active" | "archived") {
    try { await api.conversations.patch(id, { status }); if (id === activeId) setArchived(status === "archived"); void refresh(); } catch (e) { setError(e instanceof ApiError ? e.message : ERR); }
  }
  async function remove(id: string) {
    if (typeof window !== "undefined" && !window.confirm("Delete this conversation? It will be removed from your history.")) return;
    try {
      await api.conversations.remove(id);
      if (id === activeId) await fresh();
      void refresh();
    } catch (e) { setError(e instanceof ApiError ? e.message : ERR); }
  }

  useEffect(() => { void refresh(search, view); }, [search, view, refresh]);

  const submit = (e: FormEvent) => { e.preventDefault(); void send(input); };
  const onlyGreeting = messages.length > 0 && messages.every((m) => m.kind === "greeting");

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className={`card space-y-3 ${panel ? "" : "hidden lg:block"}`} aria-label="Conversation history">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">History</h2>
          <button type="button" className="btn btn-primary min-h-[34px] px-3 py-1 text-xs" onClick={() => void fresh()}>New conversation</button>
        </div>
        <label className="sr-only" htmlFor="chat-search">Search conversations</label>
        <input id="chat-search" className="input min-h-[36px] py-1 text-sm" placeholder="Search conversations…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="flex gap-2 text-xs">
          {(["active", "archived"] as const).map((v) => (
            <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className={`rounded-full border px-3 py-1 ${view === v ? "border-brand bg-brand/20" : "border-line"}`}>{v === "active" ? "Recent" : "Archived"}</button>
          ))}
        </div>
        {list.length === 0 ? <p className="text-xs text-ink-muted">{search ? "No conversations match your search." : view === "active" ? "Your conversations will appear here." : "No archived conversations."}</p> : (
          <ul className="max-h-[52vh] space-y-1 overflow-y-auto">
            {list.map((c) => (
              <li key={c.id} className={`rounded-xl border p-2 text-sm ${c.id === activeId ? "border-brand bg-brand/10" : "border-transparent hover:border-line"}`}>
                {renaming === c.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); void rename(c.id, (e.currentTarget.elements.namedItem("t") as HTMLInputElement).value); }}>
                    <input name="t" aria-label="Conversation name" className="input min-h-[32px] py-1 text-sm" defaultValue={c.title} maxLength={200} autoFocus onBlur={() => setRenaming(null)} />
                  </form>
                ) : (
                  <button type="button" className="block w-full text-left" onClick={() => void open(c.id)}>
                    <span className="block truncate font-semibold">{c.title}</span>
                    <span className="block truncate text-xs text-ink-muted">{c.preview ?? ""}</span>
                    <span className="text-[11px] text-ink-muted">{when(c.last_message_at)}</span>
                  </button>
                )}
                <div className="mt-1 flex gap-3 text-[11px] text-ink-muted">
                  <button type="button" className="hover:underline" onClick={() => setRenaming(c.id)}>Rename</button>
                  <button type="button" className="hover:underline" onClick={() => void setStatus(c.id, c.status === "archived" ? "active" : "archived")}>{c.status === "archived" ? "Restore" : "Archive"}</button>
                  <button type="button" className="hover:underline" onClick={() => void remove(c.id)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="card flex min-w-0 flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="truncate text-base font-semibold">{title || "New conversation"}</h2>
          <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs lg:hidden" onClick={() => setPanel((p) => !p)} aria-expanded={panel}>History</button>
        </div>
        {loading ? <Spinner label="Loading conversation" /> : (
          <ol aria-label="Conversation with HAN" className="space-y-4">
            {hasMore ? <li className="text-center"><button type="button" className="text-xs underline" onClick={() => void older()}>Load earlier messages</button></li> : null}
            {messages.map((m) => (
              <li key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm ${m.role === "user" ? "bg-brand text-on-brand" : "border border-line bg-wash"}`}>
                  <p className="mb-1 text-[11px] font-bold uppercase tracking-wide opacity-70">{m.role === "user" ? "You" : "HAN"}</p>
                  {m.translation ? (
                    <>
                      <p>Here is my suggested translation:</p>
                      <div className="mt-3 rounded-xl bg-surface p-4 text-ink">
                        <ReviewPanel translationId={m.translation.translation_id} canApprove={project.can_approve}
                          context={{ warnings: m.translation.warnings, tm_matches: m.translation.tm_matches, terminology: m.translation.terminology, review_note: m.translation.review_note }}
                          onOpenWorkspace={() => onOpenWorkspace(m.translation!.translation_id)} onAskHan={() => setAboutId(m.translation!.translation_id)} />
                      </div>
                      <p className="mt-3">Please review it and make any corrections before approving it.</p>
                    </>
                  ) : (
                    <>
                    <p className="whitespace-pre-wrap">{m.content}</p>
                    {m.actions?.filter((a) => a.type === "open_rhapsody" && a.path).map((a) => (
                      <a key={a.path} className="btn btn-secondary mt-2 min-h-[34px] px-3 py-1 text-xs" href={a.path ?? "#"}>{a.label ?? "Open Rhapsody"}</a>))}
                    </>
                  )}
                  {m.sources.length > 0 ? <p className="mt-2 text-xs opacity-80">Based on: {m.sources.map((s) => `${s.title}${s.version ? ` (v${s.version})` : ""}`).join("; ")}</p> : null}
                </div>
              </li>
            ))}
            {busy ? <li className="text-xs text-ink-muted" aria-live="polite">HAN is thinking…</li> : null}
            <div ref={bottom} />
          </ol>
        )}
        <div className="han-composer space-y-3">
          {error ? <Alert>{error}</Alert> : null}
          {archived ? <Alert kind="info">This conversation is archived. Restore it from the history panel to continue.</Alert> : null}
          {onlyGreeting && !busy ? (
            <div className="flex flex-wrap gap-2" aria-label="Conversation starters">
              {starters.map((s) => (
                <button key={s} type="button" className="rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-soft hover:bg-wash" onClick={() => setInput(s)}>{s}</button>
              ))}
            </div>
          ) : null}
          {aboutId ? (
            <p className="flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-xs">
              <span>HAN will use the selected translation as context for your next messages.</span>
              <button type="button" className="underline" onClick={() => setAboutId(null)}>Remove</button>
            </p>
          ) : null}
          <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="chat-input">Message to HAN</label>
            <textarea id="chat-input" className="input min-h-[64px] flex-1 resize-y" placeholder="Ask HAN anything about your translation work…" value={input} maxLength={20000}
              disabled={archived} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input); } }} />
            <button type="submit" className="btn btn-primary sm:self-end" disabled={busy || archived || !input.trim()}>{busy ? "HAN is working…" : "Send"}</button>
          </form>
          <p className="text-xs text-ink-muted">Enter sends, Shift + Enter adds a line. HAN prepares drafts only; you decide what is approved.</p>
        </div>
      </div>
    </div>
  );
}
