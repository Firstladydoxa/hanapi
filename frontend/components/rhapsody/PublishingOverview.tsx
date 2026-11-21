"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type PublishingFont, type PublishingProduction, type PublishingProfile } from "@/lib/api";
import { Spinner } from "@/components/ui";
import { AdminOnly, StagePill, stageOf } from "./publishingShared";

export function PublishingOverview() {
  const [prod, setProd] = useState<PublishingProduction[] | null>(null);
  const [fonts, setFonts] = useState<PublishingFont[]>([]);
  const [profiles, setProfiles] = useState<PublishingProfile[]>([]);
  useEffect(() => {
    void Promise.all([api.publishing.production(), api.publishing.fonts(), api.publishing.profiles()]).then(([a, b, c]) => { setProd(a); setFonts(b); setProfiles(c); }).catch(() => setProd([]));
  }, []);
  if (!prod) return <Spinner />;
  const all = prod.flatMap((e) => e.languages.map((l) => ({ ...l, edition: e.title })));
  const count = (k: string) => all.filter((l) => stageOf(l).key === k).length;
  const attention = all.filter((l) => ["submitted", "ready", "proofing"].includes(stageOf(l).key));
  const tiles = [
    { n: count("submitted") + count("ready"), label: "Waiting for you", color: "#22c55e" }, { n: count("progress"), label: "In translation", color: "#f59e0b" },
    { n: profiles.filter((p) => p.status === "active").length, label: "Active profiles", color: "#a78bfa" }, { n: fonts.length, label: "Fonts in library", color: "#38bdf8" },
  ];
  const cards = [
    { href: "/rhapsody/publishing/production", title: "Edition production", text: "Track every translation, approve submissions and generate proofs.", icon: "▤" },
    { href: "/rhapsody/publishing/profiles", title: "Typesetting profiles", text: "Fonts, sizes, margins, localization and permanent pages per language.", icon: "Aa" },
    { href: "/rhapsody/publishing/fonts", title: "Font library", text: "Browse, edit and remove the licensed fonts used for printing.", icon: "❦" },
    { href: "/rhapsody/publishing/fonts/new", title: "Add a font", text: "Upload a licensed font and preview it before it joins the library.", icon: "＋" },
  ];
  return (
    <AdminOnly>
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{tiles.map((t) => <div key={t.label} className="tile"><div className="tile-num" style={{ color: t.color }}>{t.n}</div><div className="tile-label">{t.label}</div></div>)}</div>
        <div className="grid gap-4 md:grid-cols-2">{cards.map((c) => (
          <Link key={c.href} href={c.href} className="card flex gap-4 transition hover:-translate-y-0.5">
            <span aria-hidden className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-xl font-bold bg-brand-light">{c.icon}</span>
            <span><span className="block text-base font-bold">{c.title}</span><span className="block text-sm text-ink-muted">{c.text}</span></span>
          </Link>))}</div>
        <section className="card space-y-3">
          <h2 className="text-lg font-bold">Needs your attention</h2>
          {attention.length === 0 ? <p className="text-sm text-ink-muted">Nothing is waiting. You will be notified when a translator submits.</p> : (
            <ul className="divide-y text-sm">{attention.map((l) => (
              <li key={l.assignment_id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span><strong>{l.language_name}</strong> · {l.edition} · {l.translator}</span><span className="flex items-center gap-3"><StagePill stage={stageOf(l)} /><Link className="underline text-xs" href="/rhapsody/publishing/production">Open</Link></span></li>))}</ul>)}
        </section>
      </div>
    </AdminOnly>
  );
}
