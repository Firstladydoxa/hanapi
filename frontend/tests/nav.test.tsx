import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import type { Role, User } from "@/lib/api";
import { buildNav, isActive } from "@/lib/nav";

const mocks = vi.hoisted(() => ({ path: "/projects", user: null as unknown, project: null as unknown, projectId: null as string | null }));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.path, useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return { ...actual, useAuth: () => ({ user: mocks.user, loading: false, signOut: vi.fn() }) };
});
vi.mock("@/lib/project-context", () => ({ useProject: () => ({ projectId: mocks.projectId, project: mocks.project, names: {}, loading: false, error: null, refresh: vi.fn() }) }));

const user = (role: Role): User => ({ id: "u1", email: "a@b.c", display_name: "Alice Example", role, status: "active" });
const ids = (role: Role | null, projectId: string | null = null) => buildNav(role ? user(role) : null, projectId, "Pilot").flatMap((s) => s.items.map((i) => i.id));

afterEach(cleanup);

describe("navigation model", () => {
  it("shows translators only Projects and Languages (+ the project's own pages)", () => {
    expect(ids("translator")).toEqual(["han-chat", "projects", "languages", "rhapsody", "glossary", "review"]);
    expect(ids("translator", "p1")).toEqual(["han-chat", "projects", "languages", "rhapsody", "glossary", "review", "overview", "chat", "quick", "workspace"]);
  });

  it("gates administration, operations and audit by role (convenience only: the backend enforces access)", () => {
    expect(ids("auditor")).toEqual(["han-chat", "projects", "languages", "rhapsody", "glossary", "audit"]);
    expect(ids("technical_admin")).toEqual(["han-chat", "projects", "languages", "rhapsody", "glossary", "review", "users", "admin-projects", "terminology", "knowledge", "evidence", "readiness", "publishing", "pub-production", "pub-profiles", "pub-fonts", "pub-font-new", "ops", "audit"]);
    expect(ids(null)).toEqual(["han-chat", "projects", "languages", "rhapsody", "glossary", "review"]);
  });

  it("builds per-project page links and a captioned project section", () => {
    const project = buildNav(user("translator"), "abc", "Pilot").find((s) => s.id === "project");
    expect(project?.caption).toBe("Pilot");
    expect(project?.items.map((i) => i.href)).toEqual(["/projects/abc", "/projects/abc/chat", "/projects/abc/quick", "/projects/abc/workspace"]);
  });

  it("highlights exact pages exactly and section pages by prefix", () => {
    const [overview, chat] = buildNav(user("translator"), "abc")[1]!.items;
    expect(isActive(overview!, "/projects/abc")).toBe(true);
    expect(isActive(overview!, "/projects/abc/chat")).toBe(false);
    expect(isActive(chat!, "/projects/abc/chat")).toBe(true);
    expect(isActive(chat!, "/projects/abc/chatter")).toBe(false);
    expect(isActive(buildNav(user("translator"), null)[0]!.items[0]!, "/projects/abc")).toBe(false);
  });
});

function setViewport(mobile: boolean) {
  window.matchMedia = ((q: string) => ({ matches: mobile && q.includes("700px"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia;
}
const shell = () => render(<AppShell><p>page body</p></AppShell>);
const app = () => document.querySelector(".han-app") as HTMLElement;

describe("toggleable menu", () => {
  beforeEach(() => { window.localStorage.clear(); mocks.user = user("translator"); mocks.path = "/projects/p1/chat"; mocks.projectId = "p1"; mocks.project = { id: "p1", name: "Pilot" }; });

  it("collapses to an icon rail on desktop, remembers the choice and expands again", async () => {
    setViewport(false);
    shell();
    const toggle = screen.getByRole("button", { name: "Hide navigation menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(app()).not.toHaveClass("is-collapsed");
    await act(async () => { fireEvent.click(toggle); });
    expect(app()).toHaveClass("is-collapsed");
    expect(window.localStorage.getItem("han.nav.collapsed")).toBe("1");
    const show = screen.getByRole("button", { name: "Show navigation menu" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Project chat" })).toBeInTheDocument(); // still reachable (icon + title)
    expect(screen.getByRole("link", { name: "HAN Chat" })).toHaveAttribute("href", "/chat"); // the general chat needs no project
    await act(async () => { fireEvent.click(show); });
    expect(app()).not.toHaveClass("is-collapsed");
    expect(window.localStorage.getItem("han.nav.collapsed")).toBe("0");
  });

  it("restores a collapsed menu from the previous visit", async () => {
    setViewport(false);
    window.localStorage.setItem("han.nav.collapsed", "1");
    await act(async () => { shell(); });
    expect(app()).toHaveClass("is-collapsed");
  });

  it("is an off-canvas drawer on phones: opens from the button, closes on Escape and on the backdrop", async () => {
    setViewport(true);
    await act(async () => { shell(); });
    expect(app()).not.toHaveClass("is-drawer-open");
    expect(document.getElementById("han-sidebar")).toHaveAttribute("inert");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Show navigation menu" })); });
    expect(app()).toHaveClass("is-drawer-open");
    expect(document.getElementById("han-sidebar")).not.toHaveAttribute("inert");
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(app()).not.toHaveClass("is-drawer-open");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Show navigation menu" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Close navigation" })); });
    expect(app()).not.toHaveClass("is-drawer-open");
    expect(window.localStorage.getItem("han.nav.collapsed")).toBeNull(); // the drawer never touches the desktop preference
  });

  it("marks the current page and renders the signed-in identity, without admin links for a translator", () => {
    setViewport(false);
    shell();
    expect(screen.getByRole("link", { name: "Project chat" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Quick translate" })).not.toHaveAttribute("aria-current");
    expect(screen.queryByRole("link", { name: /Users|Operations|Audit trail|Terminology/ })).toBeNull();
    expect(screen.getAllByText("Alice Example").length).toBeGreaterThan(0);
    expect(screen.getByText("page body")).toBeInTheDocument();
  });
});
