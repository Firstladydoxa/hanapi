"use client";

import { useParams } from "next/navigation";
import { EditionAdmin } from "@/components/rhapsody/EditionAdmin";
import { PageTitle } from "@/components/ui";

export default function EditionPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody of Realities Translation" title="Edition master">Upload the manuscript, let HAN lay it out in the master template, review it and activate it for translators.</PageTitle>
      <EditionAdmin editionId={id} />
    </div>
  );
}
