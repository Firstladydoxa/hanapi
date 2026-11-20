"use client";

import { PageTitle } from "@/components/ui";
import { OpsPanel } from "@/components/AdminPanels";

export default function OpsPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Technical" title="Operations">Model registry, routing, usage and system health. Restricted to technical administrators.</PageTitle>
      <OpsPanel />
    </div>
  );
}
