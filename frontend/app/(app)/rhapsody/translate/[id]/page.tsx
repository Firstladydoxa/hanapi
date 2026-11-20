"use client";

import { useParams } from "next/navigation";
import { TranslationEditor } from "@/components/rhapsody/TranslationEditor";

export default function TranslatePage() {
  const { id } = useParams<{ id: string }>();
  return <div className="han-page"><TranslationEditor assignmentId={id} /></div>;
}
