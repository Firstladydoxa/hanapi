"use client";

import { PageTitle } from "@/components/ui";
import { ProjectsPanel } from "@/components/AdminPanels";

export default function AdminProjectsPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Projects & members">Create projects, set data policy and pilot opt-in, and manage who works on each project.</PageTitle>
      <ProjectsPanel />
    </div>
  );
}
