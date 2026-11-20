"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Chat } from "@/components/Chat";
import { Crumbs, ProjectGate } from "@/components/ProjectGate";
import { PageTitle, Spinner } from "@/components/ui";

function ChatContent() {
  const router = useRouter();
  const about = useSearchParams().get("about");
  return (
    <ProjectGate>
      {({ project }) => (
        <div className="han-page">
          <Crumbs project={project} here="HAN Chat" />
          <PageTitle eyebrow={project.name} title="HAN Chat">Ask in plain language. HAN prepares drafts and answers questions; you review, edit and decide what is approved.</PageTitle>
          <Chat project={project} about={about} onOpenWorkspace={(id) => router.push(`/projects/${project.id}/workspace?translation=${encodeURIComponent(id)}`)} />
        </div>
      )}
    </ProjectGate>
  );
}

export default function ChatPage() {
  return <Suspense fallback={<Spinner label="Loading chat" />}><ChatContent /></Suspense>;
}
