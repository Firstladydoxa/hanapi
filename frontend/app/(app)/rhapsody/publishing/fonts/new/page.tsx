"use client";

import Link from "next/link";
import { AddFont } from "@/components/rhapsody/AddFont";
import { PageTitle } from "@/components/ui";

export default function AddFontPage() {
  return (
    <div className="han-page">
      <PageTitle eyebrow="Rhapsody publishing" title="Add a font">
        Only upload fonts TNI is licensed to embed in PDFs.
      </PageTitle>
      <Link className="mb-4 inline-block text-sm underline" href="/rhapsody/publishing/fonts">← Font library</Link>
      <AddFont />
    </div>
  );
}
