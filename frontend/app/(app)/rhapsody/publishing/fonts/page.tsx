"use client";

import { FontLibrary } from "@/components/rhapsody/FontLibrary";
import { PageTitle } from "@/components/ui";

export default function FontsPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody publishing" title="Font library">
        The licensed fonts HAN uses to typeset each language. Search, preview, edit details or remove fonts that are not in use.
      </PageTitle>
      <FontLibrary />
    </div>
  );
}
