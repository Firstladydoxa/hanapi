"use client";

import { EditionProduction } from "@/components/rhapsody/EditionProduction";
import { PageTitle } from "@/components/ui";

export default function ProductionPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody publishing" title="Edition production">
        Every active translation at a glance. You are notified when one is submitted; approve it, generate the proof, then approve it for publication.
      </PageTitle>
      <EditionProduction />
    </div>
  );
}
