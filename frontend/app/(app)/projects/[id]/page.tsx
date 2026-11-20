"use client";

import Link from "next/link";
import { Crumbs, ProjectGate } from "@/components/ProjectGate";
import { TierBadge } from "@/components/ui";

const ACTIONS = [
  { slug: "chat", icon: "✧", title: "HAN Chat", text: "Ask HAN for a translation in plain language. She asks one question at a time if something is missing." },
  { slug: "quick", icon: "⇄", title: "Quick translate", text: "Pick a language pair, paste your text and get a draft to review, edit and approve." },
  { slug: "workspace", icon: "▤", title: "Translation workspace", text: "Work on longer texts segment by segment, with versions, checks, terminology and Translation Memory." },
];

export default function ProjectOverviewPage() {
  return (
    <ProjectGate>
      {({ project, names }) => (
        <div className="han-page han-stack">
          <Crumbs project={project} />
          <section className="han-hero">
            <p className="han-eyebrow">{project.domain ?? "Project"}</p>
            <h1>{project.name}</h1>
            <div className="han-hero-meta">
              <span className="han-pill">{project.member_role.replace("_", " ")}</span>
              {project.style ? <span className="han-pill">Style · {project.style}</span> : null}
              <span className={`han-pill ${project.can_approve ? "han-pill-gold" : ""}`}>{project.can_approve ? "You can approve translations" : "Approval not enabled for your role"}</span>
            </div>
          </section>

          <section aria-labelledby="work-title">
            <h2 id="work-title" className="han-section-title">Start working</h2>
            <div className="han-action-grid">
              {ACTIONS.map((a) => (
                <Link key={a.slug} href={`/projects/${project.id}/${a.slug}`} className="han-action-card">
                  <span className="han-action-icon" aria-hidden>{a.icon}</span>
                  <h3>{a.title}</h3>
                  <p>{a.text}</p>
                  <span className="han-action-go">OPEN →</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="card" aria-labelledby="instr-title">
            <h2 id="instr-title" className="han-section-title">Project instructions</h2>
            <p className="whitespace-pre-wrap text-sm text-ink-soft">{project.instructions || "No special instructions."}</p>
          </section>

          <section aria-labelledby="ready-title">
            <h2 id="ready-title" className="han-section-title">Language readiness</h2>
            {project.language_directions.length === 0 ? <p className="text-sm text-ink-muted">No language pairs are available yet.</p> : null}
            <div className="han-tier-grid">
              {project.language_directions.map((d) => (
                <div key={`${d.source_code}-${d.target_code}`} className="han-tier-card">
                  <div className="han-tier-top">
                    <span>{names[d.source_code] ?? d.source_code} → {names[d.target_code] ?? d.target_code}</span>
                    <TierBadge tier={d.readiness_tier} />
                  </div>
                  {d.readiness_tier === "experimental" ? <p className="text-xs text-warn-text">Internal warning: controlled pilot only.</p> : null}
                  {d.review_note ? <p className="text-xs text-ink-muted">{d.review_note}</p> : null}
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </ProjectGate>
  );
}
