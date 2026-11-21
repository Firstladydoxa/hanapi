"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AppNotification } from "@/lib/api";

const POLL_MS = 30_000;
const DOT: Record<AppNotification["level"], string> = { info: "#38bdf8", success: "#22c55e", warning: "#f59e0b" };

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try { const r = await api.notifications.list(); setUnread(r.unread); setItems(r.items); } catch { /* keep the last list */ }
  }, []);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => { if (!document.hidden) void load(); }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function openItem(n: AppNotification) {
    setOpen(false);
    if (!n.read) { try { await api.notifications.read(n.id); } catch { /* ignore */ } void load(); }
    if (n.link) router.push(n.link);
  }
  async function readAll() { try { await api.notifications.readAll(); } catch { /* ignore */ } void load(); }

  return (
    <div className="relative" ref={box}>
      <button type="button" className="bell-btn" onClick={() => { setOpen((o) => !o); if (!open) void load(); }}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} aria-expanded={open} title="Notifications">
        <span aria-hidden>🔔</span>{unread ? <span className="bell-badge">{unread > 99 ? "99+" : unread}</span> : null}
      </button>
      {open ? (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: "var(--han-line)" }}>
            <strong className="text-sm">Notifications</strong>
            <button type="button" className="text-xs underline disabled:opacity-40" disabled={!unread} onClick={() => void readAll()}>Mark all as read</button>
          </div>
          {items.length === 0 ? <p className="px-4 py-8 text-center text-sm text-ink-muted">You&apos;re all caught up.</p> : (
            <ul>{items.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => void openItem(n)} className="flex w-full gap-3 border-b px-4 py-3 text-left hover:bg-wash" style={{ borderColor: "var(--han-line)", background: n.read ? undefined : "rgb(var(--han-primary-rgb) / .08)" }}>
                  <span aria-hidden className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: n.read ? "transparent" : DOT[n.level], border: n.read ? "1px solid var(--han-line-strong)" : "none" }} />
                  <span className="min-w-0">
                    <span className={`block text-sm ${n.read ? "" : "font-bold"}`}>{n.title}</span>
                    {n.body ? <span className="mt-0.5 block text-xs text-ink-muted">{n.body}</span> : null}
                    <span className="mt-1 block text-[11px] text-ink-muted">{ago(n.created_at)}</span>
                  </span>
                </button>
              </li>))}</ul>)}
        </div>) : null}
    </div>
  );
}
