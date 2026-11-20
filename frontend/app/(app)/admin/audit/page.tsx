"use client";

import { PageTitle } from "@/components/ui";
import { AuditPanel } from "@/components/AdminPanels";

export default function AuditPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Governance" title="Audit trail">Access, edits, approvals and administrative changes.</PageTitle>
      <AuditPanel />
    </div>
  );
}
