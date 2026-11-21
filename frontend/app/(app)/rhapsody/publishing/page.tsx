"use client";

import { PublishingOverview } from "@/components/rhapsody/PublishingOverview";
import { PageTitle } from "@/components/ui";

export default function PublishingPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody of Realities Translation" title="Rhapsody publishing">
        Everything needed to turn approved translations into print-ready editions, in one place.
      </PageTitle>
      <PublishingOverview />
    </div>
  );
}
