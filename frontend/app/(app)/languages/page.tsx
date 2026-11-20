"use client";

import { LanguagesList } from "@/components/LanguagesList";
import { PageTitle } from "@/components/ui";

export default function LanguagesPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Workspace" title="Languages">Every language HAN knows about, and how far it is enabled for translation work.</PageTitle>
      <LanguagesList />
    </div>
  );
}
