"use client";

import { GlossaryDashboard } from "@/components/GlossaryDashboard";
import { PageTitle } from "@/components/ui";

export default function GlossaryPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Workspace" title="TNI glossary">
        Approved translations of frequently translated words, expressions and sentences, kept per language by each team leader. HAN answers from these entries.
      </PageTitle>
      <GlossaryDashboard />
    </div>
  );
}
