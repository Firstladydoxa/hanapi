"use client";

import { useParams } from "next/navigation";
import { LayoutEditor } from "@/components/rhapsody/LayoutEditor";

export default function LayoutEditorPage() {
  const { id } = useParams<{ id: string }>();
  return <div className="han-page"><LayoutEditor assignmentId={id} /></div>;
}
