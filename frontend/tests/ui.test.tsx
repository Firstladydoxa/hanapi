import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewPanel } from "@/components/ReviewPanel";
import { VersionHistory } from "@/components/VersionHistory";
import { Warnings } from "@/components/Warnings";
import { buildExport } from "@/lib/export";
import { KIND_LABEL, STATUS_LABEL, versionKind } from "@/lib/labels";
import type { Job, Translation, Version } from "@/lib/api";

afterEach(cleanup);

const user = { id: "u1", display_name: "Alice" };
const version = (over: Partial<Version> = {}): Version => ({
  version_id: "v1", version_number: 1, target_text: "Hallo Welt", origin: "ai", created_by: user, created_at: "2026-01-01T10:00:00Z",
  parent_version_id: null, change_note: null, approval_state: "unapproved", approval: null, ...over,
});
const translation = (versions: Version[]): Translation => ({
  translation_id: "t1", project_id: "p1", source_language: "en", target_language: "de", source_text: "Hello world", context: null,
  status: "draft", versions, current_version_id: versions[versions.length - 1]?.version_id ?? null,
});

describe("engine confidentiality in the UI", () => {
  it("never renders provider/model/routing fields even if a payload contains them", () => {
    const leaky = {
      ...translation([{ ...version(), provider_id: "LEAK-PROVIDER", model_id: "LEAK-MODEL", route_reason: "LEAK-ROUTE", latency_ms: 91234 } as unknown as Version]),
      model_name: "LEAK-NAME",
    } as Translation;
    const context = {
      warnings: [{ type: "number", severity: "warning", message: "Numbers differ.", provider_id: "LEAK-WARN" } as never],
      tm_matches: [{ source_text: "a", target_text: "b", match_percent: 90, tm_id: "x", model_id: "LEAK-TM" } as never],
      terminology: [{ source_term: "c", target_term: "d", usage_note: null, forbidden: [], provider: "LEAK-TERM" } as never],
    };
    const { container } = render(<ReviewPanel translationId="t1" canApprove initial={leaky} context={context} />);
    const html = container.innerHTML;
    for (const marker of ["LEAK-PROVIDER", "LEAK-MODEL", "LEAK-ROUTE", "LEAK-NAME", "LEAK-WARN", "LEAK-TM", "LEAK-TERM", "91234"]) {
      expect(html).not.toContain(marker);
    }
    expect(screen.getByText("Numbers differ.")).toBeInTheDocument();
  });

  it("describes AI output only as a suggestion prepared by HAN", () => {
    render(<VersionHistory versions={[version()]} />);
    expect(screen.getByText(/Prepared by HAN/)).toBeInTheDocument();
    expect(screen.getByText(/Suggested draft/)).toBeInTheDocument();
  });
});

describe("version labelling", () => {
  it("distinguishes AI suggestion, translator-edited and approved text", () => {
    expect(versionKind({ origin: "ai", approval_state: "unapproved" })).toBe("ai");
    expect(versionKind({ origin: "human", approval_state: "unapproved" })).toBe("edited");
    expect(versionKind({ origin: "human", approval_state: "approved" })).toBe("approved");
    expect(versionKind({ origin: "ai", approval_state: "rejected" })).toBe("rejected");
    expect(KIND_LABEL.ai).not.toEqual(KIND_LABEL.edited);
  });

  it("lists versions newest first with approver and notes", () => {
    const approved = version({ version_id: "v2", version_number: 2, origin: "human", approval_state: "approved", change_note: "fixed tone",
      approval: { approver: { id: "u2", display_name: "Rita" }, decision: "approved", comment: "good", created_at: "2026-01-02T10:00:00Z" } });
    render(<VersionHistory versions={[version(), approved]} />);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Version 2 · Approved translation");
    expect(items[0]).toHaveTextContent("Approved by Rita");
    expect(items[0]).toHaveTextContent("fixed tone");
    expect(items[1]).toHaveTextContent("Version 1 · Suggested draft");
  });

  it("maps every segment status to a label", () => {
    expect(STATUS_LABEL).toEqual({ not_started: "Not started", draft: "Draft", in_review: "In review", approved: "Approved", rejected: "Rejected", needs_attention: "Needs attention" });
  });
});

describe("approval controls", () => {
  it("hides approve/reject when the member cannot approve", () => {
    render(<ReviewPanel translationId="t1" canApprove={false} initial={translation([version()])} />);
    expect(screen.queryByRole("button", { name: /approve version/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /reject/i })).toBeNull();
    expect(screen.getByText(/isn.t available to your role/i)).toBeInTheDocument();
  });

  it("offers approve only for the latest undecided version", () => {
    const { rerender } = render(<ReviewPanel translationId="t1" canApprove initial={translation([version()])} />);
    expect(screen.getByRole("button", { name: /approve version/i })).toBeEnabled();
    rerender(<ReviewPanel key="a" translationId="t1" canApprove initial={translation([version({ approval_state: "approved", origin: "human" })])} />);
    expect(screen.getByRole("button", { name: /approve version/i })).toBeDisabled();
  });

  it("requires explicit confirmation and calls the human approval endpoint", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/approve")) return new Response(JSON.stringify({ version: version({ approval_state: "approved" }), message: "Your approved translation has been saved to the project's Translation Memory." }), { status: 201 });
      return new Response(JSON.stringify(translation([version()])), { status: 200 });
    }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<ReviewPanel translationId="t1" canApprove initial={translation([version()])} />);
    await userEvent.click(screen.getByRole("button", { name: /approve version/i }));
    expect(confirm).toHaveBeenCalled();
    expect(calls.some((c) => c.includes("/approve"))).toBe(false);
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: /approve version/i }));
    expect(calls).toContain("POST /v1/versions/v1/approve");
    vi.unstubAllGlobals();
  });
});

describe("warnings and export", () => {
  it("renders an empty state without claiming correctness", () => {
    render(<Warnings warnings={[]} />);
    expect(screen.getByText(/please still review/i)).toBeInTheDocument();
  });

  it("exports approved text only unless drafts are explicitly requested", () => {
    const seg = (n: number, state: Version["approval_state"], text: string) => ({ segment_id: `s${n}`, sequence: n, source_text: "x", status: "draft" as const, warnings: [],
      current_version: version({ target_text: text, approval_state: state }) });
    const job = { job_id: "j", project_id: "p", title: null, source_language: "en", target_language: "de", status: "ready", progress: { total: 3, done: 3, approved: 1 },
      segments: [seg(1, "approved", "A"), seg(2, "unapproved", "B"), seg(3, "rejected", "C")] } as Job;
    expect(buildExport(job, false)).toEqual({ text: "A", count: 1 });
    expect(buildExport(job, true)).toEqual({ text: "A\n\nB", count: 2 });
  });
});
