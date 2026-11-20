"use client";

import { KnowledgePanel } from "@/components/KnowledgePanel";
import { PageTitle } from "@/components/ui";

export default function AdminKnowledgePage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Knowledge base">Approved TNI material HAN may use to answer questions. Nothing is used until a version is approved.</PageTitle>
      <KnowledgePanel />
    </div>
  );
}
