import type { User } from "./api";
import { canSeeAdmin, canSeeAudit, canSeeOps } from "./auth";

export interface NavItem { id: string; href: string; label: string; icon: string; exact?: boolean }
export interface NavSection { id: string; label: string; caption?: string; items: NavItem[] }

/**
 * Builds the sidebar. Which items are SHOWN depends on the role, but that is a convenience only:
 * the backend rejects every request the user is not permitted to make.
 */
export function buildNav(user: User | null, projectId: string | null, projectName?: string | null): NavSection[] {
  const sections: NavSection[] = [
    { id: "workspace", label: "WORKSPACE", items: [
      { id: "projects", href: "/projects", label: "Projects", icon: "◈", exact: true },
      { id: "languages", href: "/languages", label: "Languages", icon: "◎" },
      { id: "rhapsody", href: "/rhapsody", label: "Rhapsody of Realities", icon: "✦" },
      { id: "glossary", href: "/glossary", label: "Glossary", icon: "❝" },
      ...(user?.role === "auditor" ? [] : [{ id: "review", href: "/review", label: "Review languages", icon: "✓" }]),
    ] },
  ];
  if (projectId) {
    const base = `/projects/${projectId}`;
    sections.push({
      id: "project", label: "PROJECT", caption: projectName ?? undefined,
      items: [
        { id: "overview", href: base, label: "Overview", icon: "◇", exact: true },
        { id: "chat", href: `${base}/chat`, label: "HAN Chat", icon: "✧" },
        { id: "quick", href: `${base}/quick`, label: "Quick translate", icon: "⇄" },
        { id: "workspace", href: `${base}/workspace`, label: "Translation workspace", icon: "▤" },
      ],
    });
  }
  if (canSeeAdmin(user)) {
    sections.push({
      id: "admin", label: "ADMINISTRATION",
      items: [
        { id: "users", href: "/admin/users", label: "Users", icon: "◍" },
        { id: "admin-projects", href: "/admin/projects", label: "Projects & members", icon: "▦" },
        { id: "terminology", href: "/admin/terminology", label: "Terminology", icon: "❡" },
        { id: "knowledge", href: "/admin/knowledge", label: "Knowledge base", icon: "❖" },
        { id: "evidence", href: "/admin/evidence", label: "Language evidence", icon: "◒" },
        { id: "readiness", href: "/admin/readiness", label: "Language readiness", icon: "◐" },
      ],
    });
  }
  const system: NavItem[] = [];
  if (canSeeOps(user)) system.push({ id: "ops", href: "/admin/ops", label: "Operations", icon: "⌘" });
  if (canSeeAudit(user)) system.push({ id: "audit", href: "/admin/audit", label: "Audit trail", icon: "◷" });
  if (system.length) sections.push({ id: "system", label: "SYSTEM", items: system });
  return sections;
}

export function isActive(item: NavItem, path: string): boolean {
  return item.exact ? path === item.href : path === item.href || path.startsWith(`${item.href}/`);
}
