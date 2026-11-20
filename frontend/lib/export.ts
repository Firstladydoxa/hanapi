import type { Job } from "./api";

/** Builds a plain-text export from data already loaded in the browser. Drafts are included only when asked for. */
export function buildExport(job: Job, includeDrafts: boolean): { text: string; count: number } {
  const lines: string[] = [];
  for (const seg of job.segments) {
    const v = seg.current_version;
    if (!v) continue;
    const ok = v.approval_state === "approved" || (includeDrafts && v.approval_state === "unapproved");
    if (ok) lines.push(v.target_text);
  }
  return { text: lines.join("\n\n"), count: lines.length };
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
