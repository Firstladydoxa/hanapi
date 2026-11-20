"use client";

import { EvidencePanel } from "@/components/EvidencePanel";
import { PageTitle } from "@/components/ui";

export default function AdminEvidencePage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Language evidence">Reviewer scores and promotion readiness for each language pair.</PageTitle>
      <EvidencePanel />
    </div>
  );
}
