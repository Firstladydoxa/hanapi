"use client";

import { PageTitle } from "@/components/ui";
import { ReadinessPanel } from "@/components/AdminPanels";

export default function AdminReadinessPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Language readiness">Set the readiness tier for each language direction after it has been evaluated.</PageTitle>
      <ReadinessPanel />
    </div>
  );
}
