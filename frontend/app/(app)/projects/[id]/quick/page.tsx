"use client";

import { useRouter } from "next/navigation";
import { Crumbs, ProjectGate } from "@/components/ProjectGate";
import { QuickTranslate } from "@/components/QuickTranslate";
import { PageTitle } from "@/components/ui";

export default function QuickTranslatePage() {
  const router = useRouter();
  return (
    <ProjectGate>
      {({ project, names }) => (
        <div className="han-page-narrow">
          <Crumbs project={project} here="Quick translate" />
          <PageTitle eyebrow={project.name} title="Quick translate">Short texts: choose a language pair, paste your text and review the draft.</PageTitle>
          <QuickTranslate project={project} names={names}
            onOpenWorkspace={(id) => router.push(`/projects/${project.id}/workspace?translation=${encodeURIComponent(id)}`)} />
        </div>
      )}
    </ProjectGate>
  );
}
