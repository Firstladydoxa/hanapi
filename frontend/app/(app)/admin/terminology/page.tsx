"use client";

import { PageTitle } from "@/components/ui";
import { TerminologyPanel } from "@/components/AdminPanels";

export default function AdminTerminologyPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Terminology">Approved terms and forbidden alternatives. Only approved terms reach translators.</PageTitle>
      <TerminologyPanel />
    </div>
  );
}
