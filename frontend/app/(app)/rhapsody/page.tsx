"use client";

import { RhapsodyHome } from "@/components/rhapsody/RhapsodyHome";
import { PageTitle } from "@/components/ui";

export default function RhapsodyPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody of Realities Translation" title="Rhapsody of Realities">
        HAN lays out each monthly edition from the English manuscript and drafts the translation paragraph by paragraph, so translators review and administrators proofread.
      </PageTitle>
      <RhapsodyHome />
    </div>
  );
}
