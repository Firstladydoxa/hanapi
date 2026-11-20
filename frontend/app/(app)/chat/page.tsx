"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Chat } from "@/components/Chat";
import { PageTitle, Spinner } from "@/components/ui";

function GeneralChat() {
  const router = useRouter();
  const about = useSearchParams().get("about");
  return (
    <div className="han-page">
      <PageTitle eyebrow="HAN" title="HAN Chat">
        Ask about Pastor Chris&apos;s teaching, terminology, your glossary, how to use HAN, or where to find a feature. No project needed.
      </PageTitle>
      <Chat about={about} onOpenWorkspace={(id) => router.push(`/projects?translation=${encodeURIComponent(id)}`)} />
    </div>
  );
}

export default function ChatPage() {
  return <Suspense fallback={<Spinner label="Loading chat" />}><GeneralChat /></Suspense>;
}
