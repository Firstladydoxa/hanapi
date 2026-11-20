"use client";

import { ReviewLanguages } from "@/components/ReviewLanguages";
import { PageTitle } from "@/components/ui";

export default function ReviewPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Workspace" title="Review languages">Score HAN&apos;s drafts to help TNI decide when a language is ready.</PageTitle>
      <ReviewLanguages />
    </div>
  );
}
