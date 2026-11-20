"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { ProjectDetail } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import { Alert, Spinner } from "./ui";

interface Ctx { project: ProjectDetail; names: Record<string, string> }

/** Renders project pages once the project is loaded; shows the loading / "not found" states in one place. */
export function ProjectGate({ children }: { children: (ctx: Ctx) => ReactNode }) {
  const { project, names, error } = useProject();
  if (error) {
    return (
      <div className="han-page-narrow han-stack">
        <Alert>{error}</Alert>
        <Link href="/projects" className="btn btn-secondary">Back to projects</Link>
      </div>
    );
  }
  if (!project) return <Spinner label="Loading project" />;
  return <>{children({ project, names })}</>;
}

export function Crumbs({ project, here }: { project: ProjectDetail; here?: string }) {
  return (
    <nav aria-label="Breadcrumb" className="han-crumbs">
      <Link href="/projects">Projects</Link><span aria-hidden>/</span>
      {here ? <><Link href={`/projects/${project.id}`}>{project.name}</Link><span aria-hidden>/</span><span aria-current="page">{here}</span></> : <span aria-current="page">{project.name}</span>}
    </nav>
  );
}
