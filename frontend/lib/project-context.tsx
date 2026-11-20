"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { api, ApiError, type Language, type ProjectDetail } from "./api";

interface ProjectState {
  /** Project id taken from the URL (`/projects/<id>/...`), or null outside a project. */
  projectId: string | null;
  project: ProjectDetail | null;
  /** language code -> display name */
  names: Record<string, string>;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const Ctx = createContext<ProjectState>({ projectId: null, project: null, names: {}, loading: false, error: null, refresh: () => undefined });

export const projectIdFromPath = (path: string): string | null => /^\/projects\/([^/]+)/.exec(path)?.[1] ?? null;

/**
 * Loads the project (and the language names) for the current `/projects/<id>` URL once, so the sidebar and every
 * project page share it. The backend decides what the user may see: an unauthorised id simply returns "not found".
 */
export function ProjectProvider({ children }: { children: ReactNode }) {
  const path = usePathname();
  const projectId = projectIdFromPath(path);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [languages, setLanguages] = useState<Language[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!projectId) { setProject(null); setError(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.project(projectId), api.languages()])
      .then(([p, l]) => { if (!cancelled) { setProject(p); setLanguages(l); } })
      .catch((e: unknown) => { if (!cancelled) { setProject(null); setError(e instanceof ApiError ? e.message : "Unable to load this project."); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const names = useMemo(() => Object.fromEntries(languages.map((l) => [l.code, l.display_name])), [languages]);
  // never expose a previously loaded project under another project's URL while the new one is still loading
  const current = project && project.id === projectId ? project : null;
  const value = useMemo(() => ({ projectId, project: current, names, loading, error, refresh }), [projectId, current, names, loading, error, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useProject = (): ProjectState => useContext(Ctx);
