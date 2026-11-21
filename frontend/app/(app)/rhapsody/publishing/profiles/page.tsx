"use client";

import { ProfilesList } from "@/components/rhapsody/ProfilesList";
import { PageTitle } from "@/components/ui";

export default function ProfilesPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody publishing" title="Language typesetting profiles">
        How each language is typeset: fonts, sizes, page layout, localization and permanent content. Every save creates a revision you can restore.
      </PageTitle>
      <ProfilesList />
    </div>
  );
}
