import { describe, expect, it } from "vitest";
import { stageOf } from "@/components/rhapsody/publishingShared";

const l = (status: string, extra = {}) => ({ status, translated: 0, draft_status: "idle", has_proof: false, ...extra });

describe("production stage indicators", () => {
  it("maps each assignment state to its colour", () => {
    expect(stageOf(l("in_progress", { translated: 5 })).pill).toBe("orange");
    expect(stageOf(l("assigned", { draft_status: "running" })).pill).toBe("orange");
    expect(stageOf(l("assigned")).pill).toBe("grey");
    expect(stageOf(l("submitted")).pill).toBe("green");
    expect(stageOf(l("approved")).key).toBe("ready");
    expect(stageOf(l("approved", { has_proof: true })).key).toBe("proofing");
    expect(stageOf(l("changes_requested")).pill).toBe("red");
    expect(stageOf(l("published")).pill).toBe("blue");
  });
});
