"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Crumbs, ProjectGate } from "@/components/ProjectGate";
import { PageTitle, Spinner } from "@/components/ui";
import { Workspace } from "@/components/Workspace";

function WorkspaceContent() {
  const open = useSearchParams().get("translation");
  return (
    <ProjectGate>
      {({ project, names }) => (
        <div className="han-page-wide">
          <Crumbs project={project} here="Translation workspace" />
          <PageTitle eyebrow={project.name} title="Translation workspace">Longer texts, segment by segment. Every edit is saved as a new version; only you approve.</PageTitle>
          <Workspace project={project} names={names} openTranslationId={open} />
        </div>
      )}
    </ProjectGate>
  );
}

export default function WorkspacePage() {
  return <Suspense fallback={<Spinner label="Loading workspace" />}><WorkspaceContent /></Suspense>;
}
