"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type RegistrationLanguage, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/labels";
import { buildNav, isActive } from "@/lib/nav";
import { useProject } from "@/lib/project-context";
import { ThemeToggle } from "./ThemeToggle";
import { Spinner } from "./ui";

const STORAGE_KEY = "han.nav.collapsed";
const MOBILE_QUERY = "(max-width: 700px)";

export function Brand() {
  return (
    <Link href="/projects" className="han-brand" aria-label="HAN home">
      <span className="han-brand-mark" aria-hidden>H</span>
      <span className="han-brand-word">HAN<span className="han-brand-period">.</span></span>
    </Link>
  );
}

function ExpertiseBanner({ onSaved }: { onSaved: (u: User) => void }) {
  const [languages, setLanguages] = useState<RegistrationLanguage[]>([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.registrationLanguages().then(setLanguages).catch(() => undefined); }, []);
  async function save() {
    setBusy(true); setError(null);
    try { onSaved(await api.setExpertise(code)); } catch { setError("I couldn't save your language. Please try again."); } finally { setBusy(false); }
  }
  return (
    <div className="card mb-4 flex flex-wrap items-center gap-3 p-4" role="region" aria-label="Choose your language of expertise">
      <p className="text-sm"><strong>Choose your language of expertise.</strong> HAN uses it to open your glossary and to draft in English ⇄ your language.</p>
      <select className="input w-auto" value={code} onChange={(e) => setCode(e.target.value)} aria-label="Language of expertise">
        <option value="" disabled>Select a language…</option>
        {languages.map((l) => <option key={l.code} value={l.code}>{l.display_name}</option>)}
      </select>
      <button className="btn btn-primary" disabled={!code || busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      {error ? <span className="text-sm text-red-600">{error}</span> : null}
    </div>
  );
}

function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return mobile;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, signOut, setUser } = useAuth();
  const { projectId, project } = useProject();
  const path = usePathname();
  const mobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const sections = useMemo(() => buildNav(user, projectId, project?.name), [user, projectId, project?.name]);

  useEffect(() => {
    try { setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1"); } catch { /* storage unavailable: keep default */ }
  }, []);
  useEffect(() => { setDrawerOpen(false); }, [path]); // navigating always closes the mobile drawer
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawerOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const toggle = useCallback(() => {
    if (mobile) { setDrawerOpen((o) => !o); return; }
    setCollapsed((c) => {
      try { window.localStorage.setItem(STORAGE_KEY, c ? "0" : "1"); } catch { /* ignore */ }
      return !c;
    });
  }, [mobile]);

  const expanded = mobile ? drawerOpen : !collapsed;
  const appClass = ["han-app", collapsed && !mobile ? "is-collapsed" : "", drawerOpen ? "is-drawer-open" : ""].filter(Boolean).join(" ");

  return (
    <div className={appClass}>
      <div className="han-atmosphere" aria-hidden>
        <span className="han-orb han-orb-one" />
        <span className="han-orb han-orb-two" />
        <span className="han-grid" />
      </div>
      {drawerOpen ? <button type="button" className="han-backdrop" aria-label="Close navigation" onClick={() => setDrawerOpen(false)} /> : null}
      <aside id="han-sidebar" className="han-sidebar" aria-label="Sidebar" {...(mobile && !drawerOpen ? { inert: true } : {})}>
        <div className="han-sidebar-top">
          <Brand />
          <div className="han-product-tag">TNI · LANGUAGE INTELLIGENCE</div>
        </div>
        <nav aria-label="Main navigation" className="han-nav-scroll">
          {sections.map((section) => (
            <div key={section.id} className="han-nav-section">
              <div className="han-nav-label">{section.label}</div>
              {section.caption ? <div className="han-nav-caption" title={section.caption}>{section.caption}</div> : null}
              <div className="han-nav">
                {section.items.map((item) => {
                  const active = isActive(item, path);
                  return (
                    <Link key={item.id} href={item.href} aria-current={active ? "page" : undefined} title={item.label}
                      className={`han-nav-link ${active ? "is-active" : ""}`}>
                      <span className="han-nav-icon" aria-hidden>{item.icon}</span>
                      <span className="han-nav-text">{item.label}</span>
                      {active ? <span className="han-nav-indicator" aria-hidden /> : null}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="han-sidebar-spacer" />
        <div className="han-human-note">
          <span className="han-note-spark" aria-hidden>✦</span>
          <p className="han-note-title">Human-led by design</p>
          <p>AI prepares. People review. TNI decides.</p>
        </div>
        {user ? (
          <div className="han-profile">
            <div className="han-avatar" aria-hidden>{(user.display_name || "H").slice(0, 1).toUpperCase()}</div>
            <div className="han-profile-copy">
              <span className="han-profile-name">{user.display_name}</span>
              <span className="han-profile-role">{ROLE_LABEL[user.role] ?? user.role}</span>
            </div>
            <button type="button" className="han-signout" onClick={() => void signOut()} aria-label="Sign out" title="Sign out">↗</button>
          </div>
        ) : null}
      </aside>

      <div className="han-main-column">
        <header className="han-topbar">
          <button type="button" className="han-menu-toggle" onClick={toggle} aria-controls="han-sidebar" aria-expanded={expanded}
            aria-label={expanded ? "Hide navigation menu" : "Show navigation menu"} title={expanded ? "Hide menu" : "Show menu"}>
            <span className="han-menu-bars" aria-hidden><i /><i /><i /></span>
          </button>
          <div className="han-mobile-brand"><Brand /></div>
          <div className="han-topbar-context">
            <span className="han-live-dot" />
            <span>HUMAN-IN-THE-LOOP TRANSLATION</span>
          </div>
          <div className="han-topbar-right">
            <span className="han-secure-label"><span aria-hidden>◇</span> SECURE WORKSPACE</span>
            <ThemeToggle />
            {user ? <span className="han-topbar-user">{user.display_name}</span> : null}
          </div>
        </header>
        <main className="han-content" id="han-content">
          {user && user.role === "translator" && !user.expertise_language ? <ExpertiseBanner onSaved={setUser} /> : null}
          {loading ? <div className="han-loading"><Spinner label="Preparing your workspace" /></div> : user ? children : null}
        </main>
        <footer className="han-footer">
          <span>HAN <span className="han-brand-period">·</span> TNI LANGUAGE INTELLIGENCE</span>
          <span>AI translates. Humans understand. TNI decides.</span>
        </footer>
      </div>
    </div>
  );
}
