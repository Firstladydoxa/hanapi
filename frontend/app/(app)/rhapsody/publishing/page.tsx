"use client";

import { PublishingAdmin } from "@/components/rhapsody/PublishingAdmin";
import { PageTitle } from "@/components/ui";

export default function PublishingPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody of Realities Translation" title="Publishing fonts and languages">
        Upload the licensed fonts used by the printed Rhapsody and choose which ones HAN uses when it typesets each language.
      </PageTitle>
      <PublishingAdmin />
    </div>
  );
}
