"use client";

import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import { ProjectProvider } from "@/lib/project-context";
import { AppShell } from "@/components/AppShell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <ProjectProvider>
        <AppShell>{children}</AppShell>
      </ProjectProvider>
    </AuthProvider>
  );
}
