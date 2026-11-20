"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type ProjectListItem } from "@/lib/api";
import { Alert, EmptyState, PageTitle, Spinner } from "@/components/ui";
import { ROLE_LABEL } from "@/lib/labels";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.projects().then(setProjects).catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Unable to load projects."));
  }, []);

  return (
    <div className="han-page">
      <PageTitle eyebrow="Translator workspace" title="Your projects">Choose a project to start a translation or continue your work.</PageTitle>
      {error ? <Alert>{error}</Alert> : null}
      {!projects && !error ? <Spinner label="Loading projects" /> : null}
      {projects && projects.length === 0 ? <EmptyState title="No projects assigned">Ask your TNI administrator to add you to a project.</EmptyState> : null}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects?.map((p) => (
          <li key={p.id}>
            <Link href={`/projects/${p.id}`} className="card block h-full transition-shadow hover:shadow-md">
              <h2 className="text-lg font-semibold">{p.name}</h2>
              <p className="mt-1 text-sm text-ink-muted">{[p.domain, p.style].filter(Boolean).join(" · ") || "General"}</p>
              <p className="mt-4 inline-flex rounded-full bg-brand-light px-2.5 py-1 text-[11px] font-bold text-brand-dark">{ROLE_LABEL[p.member_role] ?? p.member_role}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
