"use client";

import { PageTitle } from "@/components/ui";
import { UsersPanel } from "@/components/AdminPanels";

export default function AdminUsersPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Administration" title="Users">Create accounts, assign roles and disable access. Generated passwords are shown once.</PageTitle>
      <UsersPanel />
    </div>
  );
}
