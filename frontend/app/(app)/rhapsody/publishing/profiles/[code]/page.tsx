"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ProfileEditor } from "@/components/rhapsody/ProfileEditor";
import { PageTitle } from "@/components/ui";

export default function ProfilePage() {
  const { code } = useParams<{ code: string }>();
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody publishing" title="Language publishing profile">
        How this language is typeset and localized. Every save creates a new revision you can restore later.
      </PageTitle>
      <Link className="text-sm underline" href="/rhapsody/publishing/profiles">← All typesetting profiles</Link>
      <ProfileEditor code={code} />
    </div>
  );
}
